import network
import time
import urequests
import json
import gc
import ntptime
import machine
import os
from machine import Pin, SPI, RTC
import ssd1322
import schedule_updater

# --- CONFIGURATION ---
WIFI_SSID = "YOUR_WIFI_SSID"
WIFI_PASS = "YOUR_WIFI_PASSWORD"
STOP_ID = "7001862" 
KVV_URL = f"http://www.kvv.de/tunnelEfaDirect.php?action=XSLT_DM_REQUEST&outputFormat=JSON&mode=direct&type_dm=any&useRealtime=1&limit=5&name_dm={STOP_ID}"
LAT = "49.2208"
LON = "8.6469"
WEATHER_URL = f"http://api.open-meteo.com/v1/forecast?latitude={LAT}&longitude={LON}&current_weather=true"

# --- DISPLAY ---
SPI_PORT = 2
SCK_PIN = 18
MOSI_PIN = 23
CS_PIN = 5
DC_PIN = 17
RST_PIN = 16

# Display reset
rst = Pin(RST_PIN, Pin.OUT)
rst.value(1)
time.sleep(0.1)
rst.value(0)
time.sleep(0.2)
rst.value(1)
time.sleep(0.5)

spi = SPI(SPI_PORT, baudrate=10000000, sck=Pin(SCK_PIN), mosi=Pin(MOSI_PIN))
display = ssd1322.SSD1322(256, 64, spi, Pin(RST_PIN), Pin(CS_PIN), Pin(DC_PIN))

# WiFi initialization
wlan = network.WLAN(network.STA_IF)
try:
    wlan.active(True)
    wlan.config(pm=0xa11140)
except:
    pass

rtc = RTC()
last_weather = "" 
update_done_today = False 

# Safe data import
try:
    import offline_data
except ImportError:
    offline_data = None 

REPLACEMENTS = {"Bahnhof": "Bhf", "Straße": "Str.", "Platz": "Pl.", "Kaiserslautern, Hauptbahnhof": "Kaiserslautern", "Kaiserslautern, Hbf": "Kaiserslautern", "Kaiserslautern, Hbf": "Kaiserslautern", "Hauptbahnhof": "Hbf",
                ", ": " "}
WIFI_BITMAP = ["   XXXXXXX   ", "  X       X  ", " X  XXXXX  X ", "X  X     X  X", "  X  XXX  X  ", "    X   X    ", "      X      "]

def shorten_text(text):
    for full, short in REPLACEMENTS.items():
        text = text.replace(full, short)
    # Limit length to 17 characters
    if len(text) > 17:
        text = text[:17] + "."
    return text

def draw_umlaut_o(x, y):
    display.pixel(x + 2, y - 1, 15)
    display.pixel(x + 5, y - 1, 15)

def draw_wifi_icon(x, y, connected):
    if connected:
        for r, s in enumerate(WIFI_BITMAP):
            for c, char in enumerate(s):
                if char == 'X':
                    display.pixel(x + c, y + r, 15)
    else:
        # Static cross
        display.line(x, y, x+9, y+8, 15)
        display.line(x+9, y, x, y+8, 15)

def wifi_reset():
    """Reset WiFi on error"""
    print("WiFi Interface Reset...")
    try:
        wlan.active(False)
        time.sleep(1)
        wlan.active(True)
        time.sleep(1)
        wlan.connect(WIFI_SSID, WIFI_PASS)
    except:
        pass

def safe_connect():
    """Connection with Internal State Error protection"""
    if wlan.isconnected():
        return True
    
    print("Connecting WiFi...")
    try:
        wlan.connect(WIFI_SSID, WIFI_PASS)
    except OSError as e:
        print(f"WiFi Error detected: {e}")
        wifi_reset()
        
    # Wait for connection
    for _ in range(10):
        if wlan.isconnected():
            return True
        time.sleep(1)
    return False

def sync_time():
    try:
        ntptime.settime()
        return True
    except:
        return False

# --- ROBUST TIME FUNCTION (Logic based, No mktime) ---
def get_cet_time():
    """
    Returns local time (tuple) for Germany (CET/CEST).
    Uses logical date comparison instead of mktime to avoid OS dependencies.
    """
    # Get UTC time
    utc = time.gmtime()
    # Unpack (year, month, day, hour)
    year, month, day, hour = utc[0], utc[1], utc[2], utc[3]

    # Gauss algorithm for last Sunday
    march_last_sunday = 31 - (int(5 * year / 4 + 4) % 7)
    oct_last_sunday = 31 - (int(5 * year / 4 + 1) % 7)

    # Logical DST determination
    # 1. Month between April and September (exclusive) -> Summer
    # 2. March: Day > last Sunday OR (Today is last Sunday AND Hour >= 1 UTC) -> Summer
    # 3. October: Day < last Sunday OR (Today is last Sunday AND Hour < 1 UTC) -> Summer
    
    is_dst = (
        (month > 3 and month < 10) or
        (month == 3 and (day > march_last_sunday or (day == march_last_sunday and hour >= 1))) or
        (month == 10 and (day < oct_last_sunday or (day == oct_last_sunday and hour < 1)))
    )

    offset = 2 if is_dst else 1
    
    # Add offset to current UTC timestamp and convert back
    return time.gmtime(time.time() + offset * 3600)

def get_static_schedule(current_h, current_m):
    if offline_data is None or not hasattr(offline_data, 'SCHEDULE'):
        return []
        
    departures = []
    for h_offset in [0, 1]:
        check_h = (current_h + h_offset) % 24
        trains = offline_data.SCHEDULE.get(check_h, [])
        for minute, line, dest in trains:
            train_time_abs = check_h * 60 + minute
            now_time_abs = current_h * 60 + current_m
            
            if check_h < current_h:
                train_time_abs += 24 * 60
            
            diff = train_time_abs - now_time_abs
            if 0 <= diff <= 90:
                short_dest = shorten_text(dest)
                departures.append({
                    'line': line,
                    'direction': short_dest,
                    'time': "{:02d}:{:02d}".format(check_h, minute),
                    'countdown': diff,
                    'is_real': False
                })
    departures.sort(key=lambda x: x['countdown'])
    return departures

def get_live_schedule():
    global last_weather
    gc.collect() 
    for attempt in range(2):
        # Weather
        if attempt == 0:
            res = None
            try:
                res = urequests.get(WEATHER_URL)
                if res.status_code == 200:
                    js = json.loads(res.text)
                    temp = js.get('current_weather', {}).get('temperature')
                    last_weather = f"{temp}C"
            except:
                pass
            finally: 
                if res:
                    try: res.close()
                    except: pass
                gc.collect() 
        
        # Transport
        res = None
        try:
            res = urequests.get(KVV_URL)
            if res.status_code == 200:
                data = json.loads(res.text)
                res.close()
                res = None
                gc.collect()
                
                parsed = []
                dep_list = data.get('departureList', [])
                del data
                
                for dep in dep_list:
                    line = dep.get('servingLine', {}).get('symbol', '?')
                    direction = dep.get('servingLine', {}).get('direction', 'Unknown')
                    if '>' in direction:
                        direction = direction.split('>')[0].strip()
                    
                    real_dt = dep.get('realDateTime', dep.get('dateTime', {}))
                    rh = int(real_dt.get('hour', 0))
                    rm = int(real_dt.get('minute', 0))
                    
                    cd_str = dep.get('countdown', '0')
                    try: cd = int(cd_str)
                    except: cd = 0
                    
                    parsed.append({
                        'line': line,
                        'direction': shorten_text(direction),
                        'time': "{:02d}:{:02d}".format(rh, rm),
                        'countdown': cd,
                        'is_real': True
                    })
                del dep_list
                gc.collect()
                return parsed
            else:
                if res: res.close()
        except OSError as e:
            error_code = e.args[0] if e.args else 0
            if error_code in [16, 118, -202]:
                wifi_reset()
            else:
                time.sleep(1)
        except Exception:
            time.sleep(1)
        finally:
            if res:
                try: res.close()
                except: pass
            gc.collect()
    return None 

def update_display(deps, time_str, online):
    display.fill(0)
    display.text("Bad Schonborn", 0, 2, 15)
    draw_umlaut_o(56, 2) 
    
    # Shifted time
    time_x = 190
    display.text(time_str, time_x + 26, 2, 15)
    
    cursor_x = 216 
    # Weather only if online
    if online and last_weather:
        w_len = len(last_weather) * 8
        cursor_x = 216 - w_len - 8
        display.text(last_weather, cursor_x, 2, 10)
    
    draw_wifi_icon(cursor_x - 21, 2, online)
    display.hline(0, 12, 256, 6)

    y = 16 
    if not deps:
        display.text("Keine Daten...", 0, 20, 15)
        if not online:
            display.text("Warte auf WiFi...", 0, 30, 10)
    else:
        if not deps[0]['is_real']:
             # Centered OFFLINE PLAN (x=64)
             display.text("* OFFLINE PLAN *", 64, 56, 10)
        
        cnt = 0
        seen = {}
        for d in deps:
            if cnt >= 4: break
            dst = d['direction']
            if seen.get(dst, 0) >= 2: continue
            seen[dst] = seen.get(dst, 0) + 1
            
            t = "sofort" if d['countdown'] == 0 else (f"in {d['countdown']} min" if d['countdown']<=9 else d['time'])
            
            display.text(d['line'], 0, y, 15)
            display.text(dst, 35, y, 10)
            # Time at new coordinate
            display.text(t, time_x, y, 15)
            
            y += 10
            cnt += 1
    display.show()

def show_status(msg):
    display.fill(0)
    display.text("System Info", 0, 2, 15)
    display.hline(0, 12, 256, 6)
    display.text(msg, 0, 30, 15)
    display.show()

def save_update_date():
    """Save current day of month to file to remember update"""
    try:
        # Use local time, not UTC
        current_day = get_cet_time()[2]
        with open('last_upd.txt', 'w') as f:
            f.write(str(current_day))
    except: pass

def check_if_updated_today():
    """Check if update was already performed today"""
    try:
        # Use local time
        current_day = get_cet_time()[2]
        with open('last_upd.txt', 'r') as f:
            saved_day = int(f.read())
            if saved_day == current_day:
                return True
    except: pass
    return False

def main():
    global update_done_today
    
    display.fill(0); display.text("System Start...", 0, 30, 15); display.show()
    print("Start")
    time.sleep(1)

    # --- 1. INITIAL CONNECTION ---
    if not safe_connect():
        while not wlan.isconnected():
            show_status("Waiting for WiFi...")
            wifi_reset()
            time.sleep(5)
    
    show_status("Syncing Time...")
    sync_time()
    
    # CHECK AFTER START
    if check_if_updated_today():
        print("Already updated today.")
        update_done_today = True

    # --- 2. FILE CHECK ---
    try:
        os.stat('offline_data.py')
    except OSError:
        show_status("Downloading Data...")
        if schedule_updater.update_from_github():
            save_update_date() # Remember date!
            # Success -> Countdown 10 sec
            for i in range(10, 0, -1):
                show_status(f"Success! Reboot {i}s")
                time.sleep(1)
            machine.reset()
        else:
            show_status("Download Failed!")
            time.sleep(2)

    last_update = 0
    reconnect_timer = 0
    last_retry_time = 0 
    
    # --- 3. MAIN LOOP ---
    while True:
        now = time.ticks_ms()
        
        # Get correct local time (CET/CEST)
        t = get_cet_time()
        h = t[3]
        m = t[4]
        time_str = "{:02d}:{:02d}".format(h, m)
        
        online = wlan.isconnected()
        
        # Reset update flag at 2 AM
        if h == 2: update_done_today = False
        
        # --- UPDATE LOGIC ---
        if h >= 3 and online and not update_done_today:
            # Pause between attempts (10 minutes)
            if time.ticks_diff(now, last_retry_time) > 600000 or last_retry_time == 0:
                show_status("Updating Schedule...")
                if schedule_updater.update_from_github():
                    save_update_date() # Record that we updated today
                    # Success -> Countdown 10 sec
                    for i in range(10, 0, -1):
                        show_status(f"Updated! Reboot {i}s")
                        time.sleep(1)
                    machine.reset()
                else:
                    last_retry_time = now # Remember failure time
                    show_status("Update Fail. Retry later.")
                    time.sleep(2)

        # --- WIFI MANAGEMENT ---
        if not online:
            if time.ticks_diff(now, reconnect_timer) > 15000:
                reconnect_timer = now
                safe_connect() 
        else:
            # Sync time once an hour (at 00 minutes)
            if t[4] == 0 and t[5] < 5:
                sync_time()

        # --- DISPLAY UPDATE ---
        if time.ticks_diff(now, last_update) > 30000:
            print("Upd...", end=" ")
            gc.collect()
            
            deps = None
            if online:
                deps = get_live_schedule()
            
            if deps:
                update_display(deps, time_str, True)
                print("Online")
            else:
                print("Offline")
                deps = get_static_schedule(h, m)
                update_display(deps, time_str, online)
            
            last_update = now
            
        time.sleep(0.5)

if __name__ == '__main__':
    main()
