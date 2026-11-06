#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import socket
import logging
import json
from http.server import HTTPServer, BaseHTTPRequestHandler

# --- НАСТРОЙКИ ---
PANELS = {
    "panel1": {"ip": "192.168.0.56", "port": 4664, "name": "Панель 1 (192.168.0.56)"},
    "panel2": {"ip": "192.168.0.62", "port": 4664, "name": "Панель 2 (192.168.0.62)"},
}
HTTP_PORT = 9999             # Порт HTTP-сервера
TIMEOUT = 3                  # Таймаут ожидания ответа (сек)
# --- КОНЕЦ НАСТРОЕК ---

# Команды из документации Lumien Standard G2
SCREEN_OFF_CMD    = bytes.fromhex('3A 30 31 53 45 30 30 30 0D')  # Экран OFF
SCREEN_ON_CMD     = bytes.fromhex('3A 30 31 53 45 30 30 31 0D')  # Экран ON
SCREEN_STATUS_CMD = bytes.fromhex('3A 30 31 47 45 30 30 30 0D')  # Запрос состояния

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)


def send_tcp_command(ip, port, command_bytes):
    """Отправляет TCP-команду на панель и ожидает ответ."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(TIMEOUT)
    try:
        sock.connect((ip, port))
        sock.sendall(command_bytes)
        logging.info(f"[{ip}] Отправлено (TCP): {command_bytes.hex(' ').upper()}")
        try:
            data = sock.recv(1024)
            if data:
                logging.info(f"[{ip}] Ответ: {data.hex(' ').upper()}")
                return True, data.hex(' ').upper(), None
            else:
                logging.info(f"[{ip}] Соединение закрыто панелью без ответа")
                return True, None, None
        except socket.timeout:
            logging.warning(f"[{ip}] Таймаут ожидания ответа")
            return True, None, "timeout"
    except Exception as e:
        logging.error(f"[{ip}] Ошибка отправки: {e}")
        return False, None, str(e)
    finally:
        sock.close()


def parse_screen_status(response_hex):
    """Разбирает ответ на запрос состояния экрана."""
    if not response_hex:
        return None
    try:
        data = bytes.fromhex(response_hex.replace(' ', ''))
        if len(data) >= 9 and data[0] == 0x3A and data[3] == 0x72 and data[4] == 0x45:
            value = data[5:8].decode('ascii', errors='ignore')
            if value == '000':
                return 'off'
            elif value == '001':
                return 'on'
            return f'unknown ({value})'
    except Exception as e:
        logging.error(f"Ошибка разбора ответа: {e}")
    return None


def command_all(command_bytes, action_name):
    """Отправляет команду всем панелям. Возвращает словарь результатов."""
    results = {}
    for key, panel in PANELS.items():
        ok, resp, err = send_tcp_command(panel["ip"], panel["port"], command_bytes)
        if ok:
            results[key] = {
                "name": panel["name"],
                "ip": panel["ip"],
                "status": "success",
                "response": resp,
                "screen": parse_screen_status(resp) if action_name == "screen_status" else None,
                "error": err,
            }
        else:
            results[key] = {
                "name": panel["name"],
                "ip": panel["ip"],
                "status": "error",
                "message": err,
            }
    return results


class LumienHTTPHandler(BaseHTTPRequestHandler):
    def _send_json(self, status_code, payload):
        self.send_response(status_code)
        self.send_header('Content-type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(payload, ensure_ascii=False).encode('utf-8'))

    def do_GET(self):
        raw_path = self.path.strip('/').lower()
        parts = raw_path.split('/')
        # Поддерживаемые форматы:
        #   /on                -> все панели
        #   /off               -> все панели
        #   /status            -> все панели
        #   /panel1/on         -> конкретная панель
        #   /panel2/off        -> конкретная панель
        #   /panel1/status     -> конкретная панель

        target = "all"
        action = raw_path

        if len(parts) == 2 and parts[0] in PANELS:
            target = parts[0]
            action = parts[1]

        # Если указана конкретная панель — работаем только с ней
        panels_to_use = PANELS if target == "all" else {target: PANELS[target]}

        if action in ('on', 'screen_on', 'display_on'):
            results = {}
            for key, panel in panels_to_use.items():
                ok, resp, err = send_tcp_command(panel["ip"], panel["port"], SCREEN_ON_CMD)
                results[key] = {
                    "name": panel["name"],
                    "ip": panel["ip"],
                    "status": "success" if ok else "error",
                    "response": resp,
                    "error": err,
                }
            self._send_json(200, {
                "action": "screen_on",
                "target": target,
                "results": results
            })

        elif action in ('off', 'screen_off', 'display_off'):
            results = {}
            for key, panel in panels_to_use.items():
                ok, resp, err = send_tcp_command(panel["ip"], panel["port"], SCREEN_OFF_CMD)
                results[key] = {
                    "name": panel["name"],
                    "ip": panel["ip"],
                    "status": "success" if ok else "error",
                    "response": resp,
                    "error": err,
                }
            self._send_json(200, {
                "action": "screen_off",
                "target": target,
                "results": results
            })

        elif action in ('status', 'state', 'screen_status'):
            results = {}
            for key, panel in panels_to_use.items():
                ok, resp, err = send_tcp_command(panel["ip"], panel["port"], SCREEN_STATUS_CMD)
                if ok:
                    results[key] = {
                        "name": panel["name"],
                        "ip": panel["ip"],
                        "status": "success",
                        "screen": parse_screen_status(resp),
                        "raw_response": resp,
                        "error": err,
                    }
                else:
                    results[key] = {
                        "name": panel["name"],
                        "ip": panel["ip"],
                        "status": "error",
                        "message": err,
                    }
            self._send_json(200, {
                "action": "screen_status",
                "target": target,
                "results": results
            })

        elif raw_path in ('', 'help'):
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(self._help_page().encode('utf-8'))

        else:
            self._send_json(404, {
                'status': 'error',
                'message': f'Неизвестный путь: /{raw_path}',
                'available': [
                    '/on', '/off', '/status',
                    '/panel1/on', '/panel1/off', '/panel1/status',
                    '/panel2/on', '/panel2/off', '/panel2/status',
                ]
            })

    def _help_page(self):
        return """<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8"><title>Lumien Control (2 панели)</title>
<style>
body{font-family:Arial,sans-serif;margin:40px;background:#f5f5f5}
h1{color:#333}
.card{background:#fff;padding:20px;margin:10px 0;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.1)}
button{padding:10px 20px;margin:4px;font-size:14px;cursor:pointer;border:none;border-radius:4px;background:#0078d4;color:#fff}
button:hover{background:#005a9e}
button.red{background:#d83b01}
button.red:hover{background:#a52a00}
#result{margin-top:10px;padding:10px;background:#f0f0f0;border-radius:4px;white-space:pre-wrap;font-family:monospace;font-size:12px}
</style></head><body>
<h1>🖥️ Lumien — управление двумя панелями</h1>

<div class="card">
  <h2>Обе панели</h2>
  <button onclick="call('/on')">Включить обе</button>
  <button class="red" onclick="call('/off')">Выключить обе</button>
  <button onclick="call('/status')">Состояние обеих</button>
</div>

<div class="card">
  <h2>Панель 1 (192.168.0.56)</h2>
  <button onclick="call('/panel1/on')">Включить</button>
  <button class="red" onclick="call('/panel1/off')">Выключить</button>
  <button onclick="call('/panel1/status')">Состояние</button>
</div>

<div class="card">
  <h2>Панель 2 (192.168.0.62)</h2>
  <button onclick="call('/panel2/on')">Включить</button>
  <button class="red" onclick="call('/panel2/off')">Выключить</button>
  <button onclick="call('/panel2/status')">Состояние</button>
</div>

<div class="card">
  <h2>Результат</h2>
  <div id="result">Нажмите кнопку…</div>
</div>

<script>
async function call(p){
  const r=document.getElementById('result');
  r.textContent='Отправка...';
  try{
    const x=await fetch(p);
    const j=await x.json();
    r.textContent=JSON.stringify(j,null,2);
  }catch(e){r.textContent='Ошибка: '+e;}
}
</script></body></html>"""

    def log_message(self, format, *args):
        logging.info(f"{self.address_string()} - {format % args}")


def main():
    server = HTTPServer(('0.0.0.0', HTTP_PORT), LumienHTTPHandler)
    logging.info(f"HTTP-сервер: http://0.0.0.0:{HTTP_PORT}")
    for key, p in PANELS.items():
        logging.info(f"  {key}: {p['name']} → {p['ip']}:{p['port']}")
    logging.info("Эндпоинты: /on /off /status | /panel1/... | /panel2/...")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("Остановка...")
    finally:
        server.server_close()


if __name__ == '__main__':
    main()