import cv2
import time
import requests
from datetime import datetime
import json
import os
from collections import deque
import imageio

# config.json dosyasını yükle
with open('config.json', 'r') as config_file:
    config = json.load(config_file)

BOT_TOKEN = config['BOT_TOKEN']
CHAT_ID = config['CHAT_ID']

DIFF_THRESHOLD = 10000

frame_buffer = deque(maxlen=200)  # ~10 saniye için 10 fps varsayımı
last_update_id = None

def set_best_resolution(cap, resolutions=None):
    if resolutions is None:
        resolutions = [
            (1920, 1080),
            (1280, 720),
            (1024, 768),
            (800, 600),
            (640, 480),
            (320, 240)
        ]
    for width, height in resolutions:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        actual_width = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        actual_height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        if int(actual_width) == width and int(actual_height) == height:
            print(f"Çözünürlük ayarlandı: {width}x{height}")
            return (width, height)
        else:
            print(f"Çözünürlük {width}x{height} desteklenmiyor, deniyor...")
    print("Desteklenen çözünürlük bulunamadı, varsayılan kullanılıyor.")
    return None

def add_timestamp_to_image(image):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.6
    font_thickness = 2
    color = (255, 255, 255)
    bg_color = (0, 0, 0)
    (w, h), _ = cv2.getTextSize(timestamp, font, font_scale, font_thickness)
    cv2.rectangle(image, (image.shape[1] - w - 10, 10), (image.shape[1] - 10, 10 + h + 10), bg_color, -1)
    cv2.putText(image, timestamp, (image.shape[1] - w - 5, 10 + h), font, font_scale, color, font_thickness)
    return image

def send_telegram_image(image, caption=""):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
        img = add_timestamp_to_image(image.copy())
        _, img_encoded = cv2.imencode('.jpg', img)
        files = {'photo': ('image.jpg', img_encoded.tobytes(), 'image/jpeg')}
        data = {'chat_id': CHAT_ID, 'caption': caption}
        requests.post(url, files=files, data=data)
    except Exception as e:
        print("Telegram gönderim hatası:", e)

def send_telegram_message(message):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {'chat_id': CHAT_ID, 'text': message}
        requests.post(url, data=data)
    except Exception as e:
        print("Telegram mesaj hatası:", e)

def send_telegram_gif(frames, fps=10):
    try:
        if len(frames) < 10:
            print("Yeterli kare yok, GIF oluşturulamadı.")
            return
        filename = 'motion.gif'
        gif_frames = [
            cv2.cvtColor(add_timestamp_to_image(f.copy()), cv2.COLOR_BGR2RGB)
            for f in frames
        ]
        imageio.mimsave(filename, gif_frames, format='GIF', fps=fps)
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
        files = {'document': (filename, open(filename, 'rb'), 'image/gif')}
        data = {'chat_id': CHAT_ID, 'caption': "🎞️ Hareketli GIF - Son 10 saniye"}
        requests.post(url, files=files, data=data)
    except Exception as e:
        print("GIF gönderim hatası:", e)

def send_telegram_video(frames, fps=10):
    try:
        height, width = frames[0].shape[:2]
        filename = 'video_output.mp4'
        out = cv2.VideoWriter(filename, cv2.VideoWriter_fourcc(*'XVID'), fps, (width, height))
        for f in frames:
            out.write(add_timestamp_to_image(f.copy()))
        out.release()
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendVideo"
        files = {'video': (filename, open(filename, 'rb'), 'video/mp4')}
        data = {'chat_id': CHAT_ID, 'caption': "🎥 Son 10 saniyelik video"}
        requests.post(url, files=files, data=data)
    except Exception as e:
        print("Video gönderim hatası:", e)

def check_telegram_commands():
    global last_update_id
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
        params = {'offset': last_update_id + 1 if last_update_id else None}
        response = requests.get(url, params=params).json()
        if not response['ok']:
            return
        for result in response['result']:
            last_update_id = result['update_id']
            if 'message' in result and 'text' in result['message']:
                text = result['message']['text']
                if text == '/foto':
                    send_telegram_image(frame_buffer[-1], caption="📷 Anlık görüntü")
                elif text == '/video10':
                    send_telegram_gif(list(frame_buffer))
                elif text == '/status':
                    now = datetime.now()
                    send_telegram_message(f"✅ Sistem çalışıyor. Saat: {now.strftime('%H:%M:%S')}")
    except Exception as e:
        print("Komut kontrol hatası:", e)

def wait_for_camera():
    print("📷 Kamera bekleniyor...")
    while True:
        cap = cv2.VideoCapture(0)
        if cap.isOpened():
            resolution = set_best_resolution(cap)
            ret, frame = cap.read()
            if ret:
                print("✅ Kamera bulundu.")
                return cap, resolution
        print("❌ Kamera yok veya çözünürlük ayarlanamadı, 5 saniye sonra tekrar denenecek...")
        cap.release()
        time.sleep(5)

while True:
    try:
        cap, resolution = wait_for_camera()
        ret, prev_frame = cap.read()
        if not ret:
            raise Exception("İlk kare alınamadı.")
        
        prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
        prev_gray = cv2.GaussianBlur(prev_gray, (21, 21), 0)
        last_hour_sent = datetime.now().hour

        print("🚀 Gözetleme başladı...")

        while True:
            ret, frame = cap.read()
            if not ret or frame is None:
                raise Exception("Kamera bağlantısı kesildi.")
            
            frame_buffer.append(frame.copy())
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (21, 21), 0)
            frame_delta = cv2.absdiff(prev_gray, gray)
            thresh = cv2.threshold(frame_delta, 25, 255, cv2.THRESH_BINARY)[1]
            motion_score = cv2.countNonZero(thresh)

            now = datetime.now()

            if motion_score > DIFF_THRESHOLD:
                print(f"[{now}] Hareket algılandı! Skor: {motion_score}")

                contours, _ = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                height, width = frame.shape[:2]
                frame_area = width * height
                frame_with_box = frame.copy()

                for contour in contours:
                    area = cv2.contourArea(contour)
                    if area < 500:
                        continue  # Gürültüleri geç
                    x, y, w, h = cv2.boundingRect(contour)
                    rect_area = w * h

                    if rect_area > frame_area * 0.7:
                        continue  # Tüm ekranı kaplayan büyük farkları yoksay

                    cv2.rectangle(frame_with_box, (x, y), (x + w, y + h), (0, 255, 0), 2)

                send_telegram_image(frame_with_box, caption="📹 Hareket algılandı!")

            if now.minute == 0 and now.hour != last_hour_sent:
                send_telegram_image(frame, caption=f"⏰ Saatlik görüntü ({now.strftime('%H:%M')})")
                last_hour_sent = now.hour

            prev_gray = gray.copy()
            check_telegram_commands()
            time.sleep(1)

    except Exception as e:
        print("⚠️ Hata oluştu:", e)
        send_telegram_message(f"⚠️ Kamera sorunu: {e}")
        try:
            cap.release()
        except:
            pass
        print("🔁 Kamera yeniden bağlanana kadar bekleniyor...")
        time.sleep(5)
