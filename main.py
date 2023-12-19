# For Raspberry Pi Pico
from usocket import socket
from machine import Pin,SPI
import network
import time
import base64
import random
import json
import traceback

led = Pin(25, Pin.OUT)
ip = '192.168.0.32'

response_codes = {
    200: 'OK',
    400: 'Bad Request',
    401: 'Unauthorized',
    404: 'Not Found',
    500: 'Internal Server Error',
    403: 'Forbidden',
}

def from_bytes(bs):
    out = 0
    for b in bs[::-1]:
        out *= 256
        out += b
    return out

class CountingStore:
    def __init__(self, max_size):
        self.current_time = int(time.time())
        self.paddings = {}
        self.times = []
        self.time_ptr = 0
        self.max_size = max_size

    def random_bytes(self, num_bytes):
        return bytes([random.randint(0, 255) for _ in range(num_bytes)])
    
    def get(self):
        curr_time = self.current_time
        rand_bytes = self.random_bytes(2)
        bs = curr_time.to_bytes(4, 'big') + rand_bytes
        self.paddings[curr_time] = rand_bytes
        if len(self.times) == self.max_size:
            to_evict = self.times[self.time_ptr]
            del self.paddings[to_evict]
            self.times[self.time_ptr] = curr_time
            self.time_ptr = (self.time_ptr + 1) % (self.max_size)
        else:
            self.times.append(curr_time)
        self.current_time = int(time.time())
        return base64.b64encode(bs).decode('ascii')
    
    def check(self, b64):
        bs = base64.b64decode(b64)
        curr_time = from_bytes(bs[:4])
        rand_bytes = bs[4:]
        if curr_time not in self.paddings:
            return False
        return self.paddings[curr_time] == rand_bytes


#W5x00 chip init
def w5x00_init():
    spi=SPI(0,2_000_000, mosi=Pin(19),miso=Pin(16),sck=Pin(18))
    nic = network.WIZNET5K(spi,Pin(17),Pin(20)) #spi,cs,reset pin
    nic.active(True)
    
    #None DHCP
    nic.ifconfig((ip,'255.255.255.0','192.168.0.1','8.8.8.8'))
    
    #DHCP
    #nic.ifconfig('dhcp')
    print('IP address :', nic.ifconfig())
    
    while not nic.isconnected():
        time.sleep(1)
        print(nic.regs())
    
def web_page():        
    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
    <meta charset="UTF-8">
    <meta http-equiv="X-UA-Compatible" content="IE=edge">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Raspberry Pi Pico Web server - WIZnet W5100S</title>
    </head>
    <body>
    <div align="center">
    <H1>Raspberry Pi Pico Web server & WIZnet Ethernet HAT</H1>
    <h2>Control LED</h2>
    <p><a href="/"><button class="button">!</button></a><br>
    </p>
    </div>
    </body>
    </html>
    """
    return html

class Request:
    def __init__(self, conn, addr):
        raw_request = conn.recv(1024)
        request_str = str(raw_request, 'utf8')
        request_lines = [l.strip() for l in request_str.split('\n')]
        self.method, self.path, self.version = request_lines[0].split(' ')
        self.client_addr, self.client_port = addr
        self.headers = {}
        i = -1
        for i, line in enumerate(request_lines[1:]):
            if not line or line[0] == '{':
                break
            k, v = line.split(': ')
            self.headers[k] = v.strip()
        self.body = None
        if (i + 1) < len(request_lines):
            self.body_lines = [l for l in request_lines[i+1:] if len(l) > 0] 
            if self.body_lines:
                # request has a body
                self.body = json.loads(''.join(self.body_lines))
    
    def __repr__(self):
        return '<Request %s %s %s>' % (self.method, self.path, self.version)
    
    def to_dict(self):
        return {
            'method': self.method,
            'path': self.path,
            'version': self.version,
            'client_addr': self.client_addr,
            'client_port': self.client_port,
            'headers': self.headers,
            'body': self.body,
        }

    def __str__(self):
        return str(self.to_dict())


def send_magic_packet():
    pass

def flash_led():
    for i in range(10):
        time.sleep(0.05)
        led.value((i+1) % 2)
    led.value(1)

def send(conn, code, content):
    conn.send('HTTP/1.1 {} {}\n'.format(code, response_codes[code]))
    conn.send('Connection: close\n')
    conn.send('Content-Type: text/html\n')
    conn.send('Content-Length: %s\n\n' % len(content))
    conn.send(content)

def serve_static(conn, path):
    try:
        with open(path, 'r') as f:
            send(conn, 200, f.read())
    except FileNotFoundError:
        send(conn, 404, 'Not Found')

def main():
    counting_store = CountingStore(10)
    led.value(1)
    s = None
    try:
        w5x00_init()
        s = socket()
        s.bind((ip, 80))
        s.listen(5)
        while True:
            conn, addr = s.accept()
            try:
                request = Request(conn, addr)
                print(str(request))
                if request.path == '/':
                    serve_static(conn, 'static/index.html')
                elif request.path == '/favicon.ico':
                    send(conn, 404, '')
                elif request.path == '/static/main.js':
                    serve_static(conn, 'static/main.js')
                elif request.path == '/wake':
                    if request.method == 'GET':
                        send(conn, 200, counting_store.get())
                
            except Exception as e2:
                print(str(e2))
                send(conn, 500, 'Internal Server Error')
            finally:
                conn.close()
                flash_led()
    except Exception as e:
        raise e
    finally:
        led.value(0)
        if s:
            s.close()
        

if __name__ == "__main__":
    main()