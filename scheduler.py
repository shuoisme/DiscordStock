# -*- coding: utf-8 -*-
"""
Render 部署用排程服務。
- FastAPI 提供 /ping 端點（讓 UptimeRobot 保持喚醒）
- /run/{session} 端點供 cron-job.org 外部觸發通知
- APScheduler 已停用（避免與 cron-job.org 同時觸發造成 yfinance rate limit）
"""
import os
import logging
from datetime import timezone, timedelta

import asyncio

import uvicorn
from fastapi import FastAPI

import main as notify
import discord_bot as dbot

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

TZ_TWN = timezone(timedelta(hours=8))
app = FastAPI(title="台股 Discord 通知排程器")


def _run(session: str):
    log.info(f"▶ 觸發場次：{session}")
    try:
        notify.main_session(session)
    except Exception as e:
        log.error(f"場次 {session} 執行失敗：{e}")


@app.on_event("startup")
async def startup():
    log.info("服務已啟動（排程由 cron-job.org 外部觸發）")
    # Discord Bot（需設定 DISCORD_BOT_TOKEN 環境變數）
    asyncio.create_task(dbot.start_bot())


@app.on_event("shutdown")
def shutdown():
    pass


# ── 端點 ────────────────────────────────────────────────────

@app.get("/")
def root():
    jobs = [{"id": j.id, "name": j.name,
             "next": str(j.next_run_time)} for j in scheduler.get_jobs()]
    return {"status": "running", "jobs": jobs}


@app.get("/ping")
def ping():
    """UptimeRobot 每 5 分鐘 ping 這裡保持服務喚醒。"""
    return "pong"


@app.get("/run/{session}")
def manual_run(session: str):
    """手動觸發特定場次（cron-job.org 或瀏覽器測試用）。"""
    if session not in ("morning", "midday1", "midday2", "close"):
        return {"error": "unknown session，可用：morning / midday1 / midday2 / close"}
    log.info(f"[HTTP] /run/{session} 收到請求，開始執行…")
    try:
        notify.main_session(session)
        log.info(f"[HTTP] /run/{session} 執行完畢")
        return {"ok": True, "session": session, "msg": "通知已發送，請查看 Discord"}
    except Exception as e:
        log.error(f"[HTTP] /run/{session} 執行失敗：{e}", exc_info=True)
        return {"ok": False, "session": session, "error": str(e)}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("scheduler:app", host="0.0.0.0", port=port)
