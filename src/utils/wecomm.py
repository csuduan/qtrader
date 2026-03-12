import json

import requests

from src.utils.logger import get_logger

logger = get_logger(__name__)

base_url = "http://8.130.149.67:8080/wecomchan?sendkey=my_key&msg_type=text"


def send_wechat(msg: str):
    data = {"msg_type": "text", "msg": msg}
    header = {"Content-Type": "application/json"}
    rsp = requests.post(base_url, data=json.dumps(data), headers=header)
    if rsp.status_code != 200 or rsp.json()["errcode"] != 0:
        logger.error(f"发送微信消息失败：{msg},{rsp.text}")
