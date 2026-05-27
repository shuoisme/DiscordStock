# -*- coding: utf-8 -*-
"""
Render 部署用排程服務。
- FastAPI 提供 /ping 端點（讓 UptimeRobot 保持喚醒）
- APScheduler 在台灣時間準時觸發四個場次的 Discord 通知
"""
import os
import logging
from datetime import timezone, timedelta

import uvicorn
from fastapi import FastAPI
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

import main as notify

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

TZ_TWN = timezone(timedelta(hours=8))
app = FastAPI(title="台股 Discord 通知排程器")

# ── 排程器 ──────────────────────────────────────────────────
scheduler = BackgroundScheduler()

def _run(session: str):
    log.info(f"▶ 觸發場次：{session}")
    try:
        notify.main_session(session)
    except Exception as e:
        log.error(f"場次 {session} 執行失敗：{e}")

TWN = "Asia/Taipei"

scheduler.add_job(_run, CronTrigger(hour=8,  minute=30, day_of_week="mon-fri", timezone=TWN),
                  args=["morning"], id="morning",  name="早盤開盤 08:30")
scheduler.add_job(_run, CronTrigger(hour=11, minute=0,  day_of_week="mon-fri", timezone=TWN),
                  args=["midday1"], id="midday1",  name="盤中觀察 11:00")
scheduler.add_job(_run, CronTrigger(hour=13, minute=0,  day_of_week="mon-fri", timezone=TWN),
                  args=["midday2"], id="midday2",  name="尾盤觀察 13:00")
scheduler.add_job(_run, CronTrigger(hour=13, minute=45, day_of_week="mon-fri", timezone=TWN),
                  args=["close"],   id="close",    name="收盤總結 13:45")


@app.on_event("startup")
def startup():
    scheduler.start()
    log.info("排程器已啟動，等待觸發時間…")
    for job in scheduler.get_jobs():
        log.info(f"  {job.name}  下次執行：{job.next_run_time}")


@app.on_event("shutdown")
def shutdown():
    scheduler.shutdown()


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
    """手動觸發特定場次（測試用，瀏覽器直接開即可）。"""
    if session not in ("morning", "midday1", "midday2", "close"):
        return {"error": "unknown session，可用：morning / midday1 / midday2 / close"}
    _run(session)
    return {"ok": True, "session": session, "msg": "通知已發送，請查看 Discord"}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("scheduler:app", host="0.0.0.0", port=port)
