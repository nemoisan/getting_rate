# -*- coding: utf-8 -*-

# pip install aiohttp 
# エラーがでたとき
# pip install aiohttp --user

import aiohttp
import asyncio
import functools
import json
import hashlib
import signal
import sys

# ******************* ここを変更 *******************
email = ""
password = ""
# ******************* ここを変更 *******************


# region 非同期タスク管理

class Runner:
    """
    非同期処理の実行およびシグナル受信時の終了とクリーンアップを行う静的クラス。
    """

    _dummy_interval = 0.1

    def __init__(self, loop=None):
        super().__init__()
        self.loop = loop if loop else asyncio.get_event_loop()

    @staticmethod
    def on_signal(_0, _1):
        # def on_signal(*_): のように記述すればパラメータ数が一致しなくて良いのだが、タイプヒントのチェックで警告が出るので、明示的に 2 パラメータとしている。
        list(map(lambda task: task.cancel(), asyncio.Task.all_tasks()))

    @staticmethod
    def stop():
        Runner.on_signal(signal.SIGTERM, None)

    @staticmethod
    def dummy_func_for_win(loop):
        # Windows で Ctrl-C を押してもシグナルが発生しない（というか処理する機会がない）ので、それに対処。
        loop.call_later(Runner._dummy_interval, functools.partial(Runner.dummy_func_for_win, loop))

    @staticmethod
    def run(tasks, loop=None) -> None:
        """
        タスクのリストを受けて、それらを非同期で実行するメソッド。

        :param tasks: タスクリスト（list ではない場合は list にされる）。
        :param loop: イベントループ。
        """
        event_loop = loop if loop else asyncio.get_event_loop()

        # Windows に対応しなくて良いのなら、このように書いた方が簡潔で綺麗ではある。
        # event_loop.add_signal_handler(signal.SIGINT, on_signal)
        # event_loop.add_signal_handler(signal.SIGTERM, on_signal)
        signal.signal(signal.SIGINT, Runner.on_signal)
        signal.signal(signal.SIGTERM, Runner.on_signal)
        event_loop.call_later(Runner._dummy_interval, functools.partial(Runner.dummy_func_for_win, event_loop))

        try:
            wait_tasks = tasks if isinstance(tasks, list) else [tasks]
            event_loop.run_until_complete(asyncio.wait(wait_tasks))
        except asyncio.CancelledError:
            pass

        # タスクのクリーンアップ。
        tasks = asyncio.gather(*asyncio.Task.all_tasks(loop=event_loop), loop=event_loop, return_exceptions=True)
        tasks.add_done_callback(lambda t: event_loop.stop())

        try:
            while not tasks.done() and not event_loop.is_closed():
                event_loop.run_forever()
        finally:
            event_loop.run_until_complete(event_loop.shutdown_asyncgens())
            event_loop.close()


# endregion


class DecurretReceiver:
    def __init__(self):
        super().__init__()

        # WebSocket セッション ID
        self.ws_session_id = ''

        # 認証キー
        self.auth_key = ''

        # ハートビート送信タスク
        self.hb_task = None

    async def send_heartbeat(self, ws):
        try:
            await ws.send_str(json.dumps({'authKey': self.auth_key, 'kind': 'ARQ', 'sessionId': self.ws_session_id}))
            while True:
                await asyncio.sleep(10)
                await ws.send_str(json.dumps({'authKey': self.auth_key, 'kind': 'BCN', 'sessionId': self.ws_session_id}))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"error in decurret heartbeat function: {e}", file=sys.stderr)

    async def connect(self):
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/73.0.3683.103 Safari/537.36'}
            async with aiohttp.ClientSession() as session:
                print('https://cx.decurret.com/decurret-frontap/')

                async with session.get('https://cx.decurret.com/decurret-frontap/', headers=headers, proxy='http://localhost:8888') as response:
                    # リダイレクト後の　URL のクエリーから HTTP セッション ID を取得し、ログイン処理を進めていく
                    print(response.url, response.url.query)
                    session_id = response.url.query['sessionid']

                payload = {'mail': email, 'password': password, 'sessionid': session_id, 'have_otp_seed': '0'}
                async with session.post('https://login.decurret.com/v1/idp/pw_auth', json=payload, headers=headers, proxy='http://localhost:8888') as response:
                    request_key = (await response.json())['request_key']

                # ここまでは正しく進んでいるように見えるが、次の POST でログインに失敗してセッションエラーになる。
                # 原因は不明。これ以前の処理に原因がある可能性も否定できない。

                headers['Content-Type'] = 'application/x-www-form-urlencoded'
                async with session.post('https://login.decurret.com/v1/idp/request_code', data=f'sessionid={session_id}&request_key={request_key}', headers=headers, proxy='http://localhost:8888') as response:
                    # レスポンス確認用
                    print(response.status, await response.text())
                    print(response.request_info.headers)

                # ユーザ ID（JavaScript ソースでは portalId などとも表記されている）を取得
                payload = '{"get_customer_list_in":{},"get_customer_control_in":{},"get_code_list_in":{"code_info_list":[{"codeKbn":"0002"},{"codeKbn":"0003"},{"codeKbn":"0009"},{"codeKbn":"0010"},{"codeKbn":"0022"},{"codeKbn":"0023"},{"codeKbn":"0039"},{"codeKbn":"0040"},{"codeKbn":"0047"},{"codeKbn":"0055"},{"codeKbn":"0107"},{"codeKbn":"0108"},{"codeKbn":"0109"}]},"get_customer_change_in":{"applStatus":"0,1,2"},"get_informations_in":{}}'
                headers['Content-Type'] = 'application/json;charset=UTF-8'
                async with session.post('https://cx.decurret.com/decurret-frontap/initialload', data=payload.encode()) as response:
                    portal_id = (await response.json())['portalId']

                # これ以降のリクエストが全部必要なのかは不明だが、なるべく忠実に再現している
                # 一つの URL に対して OPTIONS リクエストの後に POST リクエストを送る

                headers['Origin'] = 'https://cx.decurret.com'
                headers['Refer'] = 'https://cx.decurret.com/decurret-frontap/index'
                headers['Content-Type'] = 'application/json'
                headers['Sec-Fetch-Mode'] = 'cors'
                headers['Sec-Fetch-Site'] = 'same-site'

                options_headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/73.0.3683.103 Safari/537.36',
                    'Access-Control-Request-Method': 'POST',
                    'Access-Control-Request-Headers': 'content-type',
                    'Origin': 'https://cx.decurret.com',
                    'Sec-Fetch-Site': 'same-site',
                    'Referer': 'https://cx.decurret.com/decurret-frontap/index',
                }

                async with session.options('https://push.decurret.com/push-server-ws/control/connect', headers=options_headers):
                    pass

                company_id = '201'
                api_key = 'CVN0024'

                async with session.post('https://push.decurret.com/push-server-ws/control/connect', headers=headers, data=f'{{"channel":"24","companyId":"{company_id}","appliVer":"0040010002","apiKey":"{api_key}"}}') as response:
                    j = await response.json()
                    auth_seed = j['authSeed']
                    self.ws_session_id = j['sessionId']

                self.auth_key = hashlib.md5(':'.join([company_id, api_key, auth_seed, self.ws_session_id]).encode()).hexdigest()

                headers['Authorization'] = self.auth_key

                async with session.options('https://push.decurret.com/push-server-ws/control/login', headers=options_headers):
                    pass

                async with session.post('https://push.decurret.com/push-server-ws/control/login', headers=headers, json={'userId': portal_id, 'sessionId': self.ws_session_id}) as response:
                    print(response.status, response.url, await response.text())

                async with session.options('https://push.decurret.com/push-server-ws/control/filtering', headers=options_headers):
                    pass
                # print(response.status_code, response.text)

                async with session.post('https://push.decurret.com/push-server-ws/control/filtering', headers=headers, json={"sessionId": self.ws_session_id, "symbolCodes": ["2001", "2008", "2003", "2002", "2004"]}) as response:
                    print(response.status, response.url, await response.text())

                # 最後のリクエストヘッダの Cookie を流用して WS にセット

                # cookie = response.request_info.headers['Cookie']

                url = 'wss://push.decurret.com/push-server-ws/wsock'

                async with session.ws_connect(url, headers=headers) as ws:
                    self.hb_task = asyncio.ensure_future(self.send_heartbeat(ws))
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            print(msg.data)
        except asyncio.CancelledError:
            if self.hb_task:
                await self.hb_task
        except Exception as e:
            print(f"error in decurret WebSocket connection: {e}", file=sys.stderr)


def main():
    receiver = DecurretReceiver()
    try:
        Runner.run(receiver.connect())
    except Exception as e:
        print(f"error in decurret WebSocket receiver: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
