import json
from datetime import datetime

import requests

from qtrader.utils.logger import get_logger

logger = get_logger(__name__)

base_url = "http://8.130.149.67:8080/wecomchan?sendkey=my_key&msg_type=text"


def is_dnd_now(dnd_start: int = 23, dnd_end: int = 8) -> bool:
    """
    判断当前是否处于免打扰时间段

    Args:
        dnd_start: 免打扰开始小时（如23表示23:00）
        dnd_end: 免打扰结束小时（如8表示08:00）
                   相同值表示全天免打扰

    Returns:
        True 表示当前在免打扰时段
    """
    if dnd_start == dnd_end:
        # 全天免打扰
        return True
    now_hour = datetime.now().hour
    if dnd_start > dnd_end:
        # 跨天模式（如 23:00-08:00）
        return now_hour >= dnd_start or now_hour < dnd_end
    else:
        # 同天模式（如 12:00-14:00）
        return dnd_start <= now_hour < dnd_end


def send_wechat(msg: str):
    data = {"msg_type": "text", "msg": msg}
    header = {"Content-Type": "application/json"}
    rsp = requests.post(base_url, data=json.dumps(data), headers=header)
    if rsp.status_code != 200 or rsp.json()["errcode"] != 0:
        logger.error(f"发送微信消息失败：{msg},{rsp.text}")
