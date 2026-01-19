#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
慧生活798 签到任务脚本
适配青龙面板

环境变量:
    HUI798_TOKEN - 登录 token, 多账号用 & 或 @ 或 换行 分隔
    HUI798_KEY - 卡密 (用于验证)

cron: 0 8 * * *
new Env('慧生活798');
"""

import os
import time
import requests
from datetime import datetime, timezone, timedelta

BASE_URL = "https://i.ilife798.com/api/v1"
SIGN_URL = "https://hui798.llol.xyz"
DEFAULT_HEADERS = {
    "Content-Type": "application/json; charset=UTF-8",
    "applicationtype": "1,1",
    "versioncode": "2.0.15",
}
BJ_TZ = timezone(timedelta(hours=8))


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def get_env(key, default=""):
    return os.environ.get(key, default)


def sleep(seconds):
    time.sleep(seconds)


def now_bj():
    return datetime.now(BJ_TZ)


def date_bj(ts_ms=None):
    if ts_ms is None:
        return now_bj().strftime("%Y-%m-%d")
    return datetime.fromtimestamp(ts_ms / 1000, BJ_TZ).strftime("%Y-%m-%d")


def weekday_bj():
    return now_bj().isoweekday()


def get_worker_tasks(sign_url):
    try:
        url = f"{sign_url}/tasks"
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if data.get("code") == 0:
            return data.get("data", {})
    except Exception as e:
        log(f"[-] 获取任务列表失败: {e}")
    return {}


def get_sign_by_task(sign_url, task_name, token, uid, card_key=None):
    url = f"{sign_url}/sign"
    payload = {"task": task_name, "token": token, "uid": uid}
    if card_key:
        payload["key"] = card_key
    resp = requests.post(url, json=payload, timeout=10)
    data = resp.json()
    
    if data.get("code") == -2:
        raise Exception(f"卡密验证失败: {data.get('error', '未知错误')}")
    
    if data.get("code") != 0:
        raise Exception(f"获取签名失败: {data.get('error', data)}")
    
    return data["data"]["sign"], data["data"]["adId"]


def get_account_info(token):
    headers = {**DEFAULT_HEADERS, "authorization": token}
    resp = requests.get(f"{BASE_URL}/ui/app/master", headers=headers, timeout=10)
    return resp.json()


def get_score_info(token):
    headers = {**DEFAULT_HEADERS, "authorization": token}
    resp = requests.get(f"{BASE_URL}/acc/score/mission-lst", headers=headers, timeout=10)
    return resp.json()


def get_score_records(token, page=0, size=50):
    headers = {**DEFAULT_HEADERS, "authorization": token}
    url = f"{BASE_URL}/acc/score/score-lst?page={page}&size={size}&hasCount=true"
    resp = requests.get(url, headers=headers, timeout=10)
    return resp.json()


def get_today_score(token):
    today = date_bj()
    total_score = 0
    details = []
    
    try:
        resp = get_score_records(token, page=0, size=50)
        if resp.get("code") != 0:
            return 0, []
        
        records = resp.get("data", [])
        for record in records:
            create_time = record.get("ctime", 0)
            if create_time:
                record_date = date_bj(create_time)
                if record_date == today:
                    record_data = record.get("data", {})
                    score = int(record_data.get("score", 0))
                    if score > 0:
                        total_score += score
                        name = record_data.get("adName", "") or record.get("msg", "") or "未知"
                        details.append({"name": name, "score": score})
                elif record_date < today:
                    break
    except Exception as e:
        log(f"[-] 获取积分记录失败: {e}")
    
    return total_score, details


def execute_task_by_name(sign_url, token, uid, task_name, add_score, add_score_type=2, card_key=None):
    sign, ad_id = get_sign_by_task(sign_url, task_name, token, uid, card_key)
    
    task_data = {
        "adId": ad_id,
        "addScore": add_score,
        "addScoreType": add_score_type,
        "type": 101,
    }
    
    headers = {**DEFAULT_HEADERS, "authorization": token}
    url = f"{BASE_URL}/acc/score/score-send?sign={sign}"
    resp = requests.post(url, headers=headers, json=task_data, timeout=10)
    return resp.json()


def check_daily_signed(week_mask):
    weekday = weekday_bj()
    today_mask = 1 << (weekday - 1)
    return (week_mask & today_mask) != 0


def daily_check_in(sign_url, token, uid, daily_config, card_key=None):
    weekday = weekday_bj()
    sign, ad_id = get_sign_by_task(sign_url, "checkin", token, uid, card_key)
    
    score = daily_config.get("score", 5)
    task_data = {
        "adId": ad_id,
        "addScore": score,
        "addScoreType": 1,
        "weekday": weekday,
    }
    
    headers = {**DEFAULT_HEADERS, "authorization": token}
    url = f"{BASE_URL}/acc/score/score-send?sign={sign}"
    resp = requests.post(url, headers=headers, json=task_data, timeout=10)
    return resp.json()


def run_account(sign_url, token, index, worker_tasks, card_key=None):
    log(f"")
    log(f"========== 账号 {index + 1} ==========")
    
    results = []
    
    try:
        account_info = get_account_info(token)
        if account_info.get("code") != 0:
            log(f"[X] 获取账号信息失败: {account_info.get('msg', account_info)}")
            if account_info.get("code") == -99:
                log("[!] Token 已过期, 请重新获取")
            return {"success": False, "msg": "获取账号信息失败"}
        
        acc_data = account_info.get("data", {}).get("account", {})
        uid = acc_data.get("id") or acc_data.get("uid")
        nickname = acc_data.get("name") or acc_data.get("nickname") or "未知"
        phone = acc_data.get("pn", "")
        
        log(f"[*] 账号: {nickname} ({phone})")
        log(f"[*] UID: {uid}")
        
        if not uid:
            log("[X] 获取 UID 失败, Token 可能已过期")
            return {"success": False, "msg": "UID 为空"}
        
        log("")
        log("[*] 获取积分信息...")
        score_resp = get_score_info(token)
        if score_resp.get("code") != 0:
            log(f"[-] 获取积分信息失败: {score_resp.get('msg', score_resp)}")
        
        resp_data = score_resp.get("data", {})
        acc_score = resp_data.get("accScoreRsp", {})
        daily_rsp = resp_data.get("dailyRSP", {})
        
        score = acc_score.get("score", "0")
        total_score = acc_score.get("totalScore", "0")
        log(f"[*] 当前积分: {score}, 累计积分: {total_score}")
        
        log("")
        log("[*] 执行每日签到...")
        daily_info = acc_score.get("daily", {})
        week_mask = daily_info.get("week", 0)
        
        if check_daily_signed(week_mask):
            log("[*] 今日已签到, 跳过")
            results.append({"task": "每日签到", "success": True, "msg": "已签到"})
        else:
            try:
                result = daily_check_in(sign_url, token, uid, daily_rsp, card_key)
                if result.get("code") == 0:
                    got_score = result.get("data", {}).get("score", daily_rsp.get("score", 5))
                    log(f"[+] 签到成功, 获得 {got_score} 积分")
                    results.append({"task": "每日签到", "success": True})
                else:
                    log(f"[-] 签到失败: {result.get('msg', result)}")
                    results.append({"task": "每日签到", "success": False, "msg": result.get("msg")})
            except Exception as e:
                log(f"[-] 签到异常: {e}")
                results.append({"task": "每日签到", "success": False, "msg": str(e)})
        
        sleep(1)
        
        for task_key, task_config in worker_tasks.items():
            task_name = task_config.get("name", task_key)
            task_score = task_config.get("score", 20)
            task_limit = task_config.get("limit", 1)
            task_type = task_config.get("type", 2)
            
            log(f"")
            log(f"[*] {task_name} ({task_limit}次, {task_score}积分/次)")
            
            for i in range(task_limit):
                retry_count = 0
                max_retry = 3
                
                while retry_count < max_retry:
                    try:
                        result = execute_task_by_name(sign_url, token, uid, task_key, task_score, task_type, card_key)
                        if result.get("code") == 0:
                            got_score = result.get("data", {}).get("score", task_score)
                            log(f"    [{i+1}/{task_limit}] 成功, +{got_score} 积分")
                            results.append({"task": f"{task_name}_{i+1}", "success": True})
                            break
                        elif result.get("code") == -1:
                            log(f"    [{i+1}/{task_limit}] {result.get('msg', '任务不可用')}")
                            results.append({"task": f"{task_name}_{i+1}", "success": False})
                            break
                        elif "请求过于频繁" in result.get("msg", ""):
                            retry_count += 1
                            if retry_count < max_retry:
                                sleep(5)
                                continue
                            else:
                                log(f"    [{i+1}/{task_limit}] 失败: 请求过于频繁, 重试{max_retry}次后放弃")
                                results.append({"task": f"{task_name}_{i+1}", "success": False})
                                break
                        else:
                            log(f"    [{i+1}/{task_limit}] 失败: {result.get('msg', result)}")
                            results.append({"task": f"{task_name}_{i+1}", "success": False})
                            break
                    except Exception as e:
                        err_msg = str(e)
                        log(f"    [{i+1}/{task_limit}] 异常: {err_msg}")
                        results.append({"task": f"{task_name}_{i+1}", "success": False})
                        if "卡密验证失败" in err_msg:
                            return {"success": False, "msg": err_msg, "results": results}
                        break
                
                if i < task_limit - 1:
                    sleep(5)
            
            sleep(2)
        
        success_count = len([r for r in results if r.get("success")])
        log(f"")
        log(f"[*] 全部完成: 成功 {success_count}/{len(results)}")
        
        log(f"")
        log(f"[*] 查询今日积分...")
        today_score, details = get_today_score(token)
        if today_score > 0:
            log(f"[*] 今日获得: {today_score} 积分")
        else:
            log(f"[-] 今日暂无积分记录")
        
        return {"success": True, "results": results}
        
    except Exception as e:
        log(f"[-] 执行异常: {e}")
        return {"success": False, "msg": str(e)}


def main():
    log("=" * 40)
    log("慧生活798 签到任务")
    log("=" * 40)
    log(f"执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    sign_url = SIGN_URL
    card_key = get_env("HUI798_KEY")
    
    worker_tasks = get_worker_tasks(sign_url)
    if not worker_tasks:
        log("[X] 无法获取任务配置, 请检查签名服务")
        return
    
    token_env = get_env("HUI798_TOKEN")
    if not token_env:
        log("[X] 未配置 HUI798_TOKEN 环境变量")
        return
    
    tokens = [t.strip() for t in token_env.replace("&", "\n").replace("@", "\n").split("\n") if t.strip()]
    log(f"[*] 共 {len(tokens)} 个账号")
    
    all_results = []
    
    for i, token in enumerate(tokens):
        result = run_account(sign_url, token, i, worker_tasks, card_key)
        all_results.append(result)
        
        if result.get("msg", "").startswith("卡密验证失败"):
            break
        
        if i < len(tokens) - 1:
            log("")
            log("[*] 等待 2 秒后执行下一个账号...")
            sleep(2)
    
    log("")
    log("=" * 40)
    log("执行汇总")
    log("=" * 40)
    success_accounts = len([r for r in all_results if r.get("success")])
    log(f"[*] 成功账号: {success_accounts}/{len(tokens)}")
    
    log("")
    log("[*] 慧生活798 执行完成")


if __name__ == "__main__":
    main()
