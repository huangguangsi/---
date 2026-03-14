import time
import random
import json
import umqtt.simple as mqtt
import network
import machine
from machine import UART, Pin
import dht

# 串口配置（以UART2为例，根据硬件调整引脚）
UART_ID = 2
BAUD_RATE = 115200
TX_PIN = 17
RX_PIN = 16
# 硬件配置
DHT_PIN = 15
MQ2_PIN = 34
MQ7_PIN = 35
FLAME_PIN = 32  # 新增：火焰传感器引脚

# 传感器校准参数（需手动测量）
# MQ - 2 校准参数
CLEAN_AIR_MQ2 = 1100
SMOKE_MAX_MQ2 = 3500
# MQ - 7 校准参数
CLEAN_AIR_MQ7 = 1000
CO_MAX_MQ7 = 3000

# 温度异常阈值
TEMPERATURE_THRESHOLD = 35 

# 初始化UART
uart = UART(UART_ID, baudrate=BAUD_RATE, tx=Pin(TX_PIN), rx=Pin(RX_PIN),
            bits=8, parity=None, stop=1, timeout=1000)

# Wi-Fi 配置
WIFI_SSID = "TP-LINK_9585"
WIFI_PASSWORD = "12345678"

# MQTT 配置
MQTT_CLIENT_ID = "esp32_receiver_" + str(time.time())[:6]
MQTT_BROKER = "27.106.98.19"
MQTT_PORT = 1883
SENSOR_TOPIC = "sensors/room1"
DEVICE_TOPIC = "devices/room1"
RECEIVE_TOPIC = "sensors/kitchen"

# 用于存储订阅得到的 status 值
sub_status = 1  

def connect_wifi():
    sta_if = network.WLAN(network.STA_IF)
    sta_if.active(True)
    if sta_if.isconnected():
        return True
    print(f"连接 Wi-Fi: {WIFI_SSID}")
    sta_if.connect(WIFI_SSID, WIFI_PASSWORD)
    for _ in range(20):
        if sta_if.isconnected():
            print(f"Wi-Fi 连接成功！IP: {sta_if.ifconfig()[0]}")
            return True
        time.sleep(0.5)
    print("Wi-Fi 连接失败！")
    return False


def read_dht11():
    d = dht.DHT11(machine.Pin(DHT_PIN))
    try:
        d.measure()
        return {
            "temperature": d.temperature(),
            "humidity": d.humidity()
        }
    except Exception as e:
        print("DHT11 读取错误:", e)
        return None


def read_mq2():
    adc = machine.ADC(machine.Pin(MQ2_PIN))
    adc.atten(machine.ADC.ATTN_11DB)
    samples = [adc.read() for _ in range(10)]
    raw_value = sum(samples) // 10
    if SMOKE_MAX_MQ2 > CLEAN_AIR_MQ2:
        smoke_percent = ((raw_value - CLEAN_AIR_MQ2) / (SMOKE_MAX_MQ2 - CLEAN_AIR_MQ2)) * 100
    else:
        smoke_percent = 0
    return max(0, min(100, smoke_percent))


def read_mq7():
    adc = machine.ADC(machine.Pin(MQ7_PIN))
    adc.atten(machine.ADC.ATTN_11DB)
    samples = [adc.read() for _ in range(10)]
    raw_value = sum(samples) // 10
    if CO_MAX_MQ7 > CLEAN_AIR_MQ7:
        co_percent = ((raw_value - CLEAN_AIR_MQ7) / (CO_MAX_MQ7 - CLEAN_AIR_MQ7)) * 100
    else:
        co_percent = 0
    return max(0, min(100, co_percent))


def read_flame_sensor():
    flame_sensor = Pin(FLAME_PIN, Pin.IN)
    return flame_sensor.value()  # 返回0或1，0表示检测到火焰，1表示未检测到火焰


def generate_sensor_data():
    dht_data = read_dht11()
    smoke_percent = read_mq2()
    co_percent = read_mq7()
    flame_status = read_flame_sensor()  # 新增：获取火焰传感器状态
    if dht_data and smoke_percent is not None and co_percent is not None:
        return {
            "status": get_status(dht_data["temperature"], smoke_percent, co_percent, flame_status),  # 传递火焰状态给状态判断函数
            "co": round(co_percent, 1),
            "smoke": round(smoke_percent, 1),
            "temperature": dht_data["temperature"],
            "humidity": dht_data["humidity"],
            "flame": flame_status  # 新增：将火焰状态添加到传感器数据中
        }
    return None


def get_status(temperature, smoke_percent, co_percent, flame_status):
    abnormal_count = 0
    if temperature > TEMPERATURE_THRESHOLD:
        abnormal_count += 1
    if smoke_percent >= 15:  # 使用之前设定的阈值
        abnormal_count += 1
    if co_percent >= 15:  # 使用之前设定的阈值
        abnormal_count += 1
    if flame_status == 0:
        abnormal_count += 1

    if abnormal_count == 0:
        return 0
    elif abnormal_count == 1:
        return 1
    elif abnormal_count == 2:
        return 2
    elif abnormal_count == 3:
        return 3
    else:
        return 4


def generate_device_status():
    return {
        "battery": max(0, min(100, random.randint(-5, 105))),
        "extinguisher": random.randint(0, 100),
        "mode": random.choice(["auto", "manual"]),
        "location": random.choice(["客厅", "卧室", "厨房", "阳台"])
    }


def sub_cb(topic, msg):
    global sub_status
    try:
        topic_str = topic.decode("utf-8")
        msg_str = msg.decode("utf-8")
        data = json.loads(msg_str)
        print(f"\n--- 实时接收 ---")
        print(f"主题: {topic_str}")
        print(f"原始消息: {msg_str}")
        print(f"解析数据: {data}")
        if "status" in data:
            sub_status = data["status"]
    except json.JSONDecodeError:
        print(f"[错误] JSON 解码失败！原始消息: {msg_str}")
    except Exception as e:
        print(f"[错误] 消息处理异常: {e}")


def uart_send(data):
    if isinstance(data, int):
        # 将整数转换为 16 进制整数（在 Python 中实际是按 16 进制解释）
        hex_int = data
        uart.write(bytes([hex_int]))  # 将整数转换为字节形式发送
    elif isinstance(data, str):
        data = data.encode()
        uart.write(data)
    elif not isinstance(data, (bytes, bytearray)):
        raise TypeError("Unsupported data type. Expected int, str, bytes or bytearray.")


def uart_read():
    data = uart.read()
    if data:
        return data.decode().strip()
    return None


def main():
    if not connect_wifi():
        return

    client = None
    try:
        client = mqtt.MQTTClient(
            client_id=MQTT_CLIENT_ID,
            server=MQTT_BROKER,
            port=MQTT_PORT,
            keepalive=300
        )
        client.set_callback(sub_cb)
        client.connect()
        print(f"已订阅主题: {RECEIVE_TOPIC}")
        client.subscribe(RECEIVE_TOPIC)

        print("传感器预热中...（请保持环境无烟雾和 CO）")
        time.sleep(10)

        while True:
            received_data = uart_read()
            if received_data:
                print(f"接收到数据：{received_data}")
                time.sleep(0.1)

            sensor_data = generate_sensor_data()
            if sensor_data:
                try:
                    msg = json.dumps(sensor_data).encode('utf-8')
                    client.publish(
                        topic=SENSOR_TOPIC,
                        msg=msg,
                        retain=False
                    )
                    print(f"[传感器数据] {sensor_data}")
                except Exception as e:
                    print(f"传感器数据 JSON 编码错误: {e}")

                status = sensor_data["status"]
                if status > 0 or sub_status > 0:
                    send_status = status if status > 0 else sub_status
                    uart_send(send_status)
                else:
                    uart_send(0)

            if random.randint(1, 3) == 1:
                device_status = generate_device_status()
                try:
                    msg = json.dumps(device_status).encode('utf-8')
                    client.publish(
                        topic=DEVICE_TOPIC,
                        msg=msg,
                        retain=False
                    )
                    print(f"[设备状态] {device_status}")
                except Exception as e:
                    print(f"设备状态数据 JSON 编码错误: {e}")

            client.check_msg()
            time.sleep(0.01)
            time.sleep(5)

    except Exception as e:
        print(f"\n[致命错误] {e}，5 秒后重试...")
        time.sleep(5)
    finally:
        if client:
            client.disconnect()


if __name__ == "__main__":
    main()