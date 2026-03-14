import time
import random
import json
import umqtt.simple as mqtt
import network
import machine
from machine import UART, Pin
import time
import dht


# 串口配置（以UART2为例，根据硬件调整引脚）
UART_ID = 2          # UART编号（ESP32支持多个UART，如0、1、2）
BAUD_RATE = 115200    # 波特率
TX_PIN = 17          # 发送引脚（TX）
RX_PIN = 16          # 接收引脚（RX）
# 硬件配置
DHT_PIN = 12          # DHT11 传感器引脚
MQ2_PIN = 34          # MQ - 9 传感器模拟输出引脚
MQ7_PIN = 35          # MQ - 7 传感器模拟输出引脚（新增）
MQ9_PIN = 33          # MQ - 2 传感器模拟输出引脚（新增）

# 传感器校准参数（需手动测量）
# MQ - 2 校准参数
CLEAN_AIR_MQ2 = 550   # 清洁空气中 MQ - 2 的 ADC 平均值
SMOKE_MAX_MQ2 = 3500  # 烟雾环境中 MQ - 2 的 ADC 最大值
# MQ - 7 校准参数（需在清洁空气和高浓度 CO 环境下测量）
CLEAN_AIR_MQ7 = 1240  # 清洁空气中 MQ - 7 的 ADC 平均值（无 CO 时）
CO_MAX_MQ7 = 3000     # 高浓度 CO 环境中 MQ - 7 的 ADC 最大值（需校准）
# MQ - 9 校准参数（需在清洁空气和高浓度天然气环境下测量）
CLEAN_AIR_MQ9 = 1000  # 清洁空气中 MQ - 9 的 ADC 平均值
GAS_MAX_MQ9 = 3000     # 高浓度天然气环境中 MQ - 9 的 ADC 最大值

# 异常阈值
TEMPERATURE_THRESHOLD = 40  # 温度异常阈值（℃）
SMOKE_THRESHOLD = 30        # 烟雾浓度异常阈值（%）
CO_THRESHOLD = 30           # CO 浓度异常阈值（%）
GAS_THRESHOLD = 30          # 天然气浓度异常阈值（%）

# 初始化UART
uart = UART(UART_ID, baudrate=BAUD_RATE, tx=Pin(TX_PIN), rx=Pin(RX_PIN),
            bits=8, parity=None, stop=1, timeout=1000)

# Wi-Fi 配置
WIFI_SSID = "TP-LINK_9585"
WIFI_PASSWORD = "12345678"

# MQTT 配置
MQTT_CLIENT_ID = "esp32mqtt_DHT11_MQ2_MQ7_MQ9"  # 更新客户端 ID
MQTT_BROKER = "27.106.98.19"
MQTT_PORT = 1883
SENSOR_TOPIC = "sensors/kitchen"


def uart_send(data):
    """发送数据到串口"""
    if isinstance(data, str):
        data = data.encode()  # 字符串转字节
    uart.write(data)


def uart_read():
    """读取串口数据（非阻塞）"""
    data = uart.read()  # 读取所有可用数据（返回bytes类型）
    if data:
        return data.decode().strip()  # 转字符串并去除首尾空格
    return None


def connect_wifi():
    """连接 Wi-Fi（带超时机制）"""
    sta_if = network.WLAN(network.STA_IF)
    sta_if.active(True)
    if sta_if.isconnected():
        return True

    print(f"正在连接 Wi-Fi: {WIFI_SSID}")
    sta_if.connect(WIFI_SSID, WIFI_PASSWORD)

    for _ in range(15):
        if sta_if.isconnected():
            print("Wi-Fi 连接成功")
            print("IP 地址:", sta_if.ifconfig()[0])
            return True
        time.sleep(0.5)

    print("Wi-Fi 连接失败，请检查 SSID/密码")
    return False


def read_dht11():
    """读取 DHT11 温湿度数据"""
    d = dht.DHT11(machine.Pin(DHT_PIN))
    try:
        d.measure()
        return {
            "temperature": d.temperature(),       # 温度（℃）
            "humidity": d.humidity()        # 湿度（%RH）
        }
    except Exception as e:
        print("DHT11 读取错误:", e)
        return None


def read_mq2():
    """读取 MQ - 2 烟雾浓度（百分比）"""
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
    """读取 MQ - 7 CO 浓度（百分比，需校准）"""
    adc = machine.ADC(machine.Pin(MQ7_PIN))
    adc.atten(machine.ADC.ATTN_11DB)
    samples = [adc.read() for _ in range(10)]
    raw_value = sum(samples) // 10

    # 转换为 CO 浓度百分比（0 - 100%，实际需根据传感器特性校准）
    if CO_MAX_MQ7 > CLEAN_AIR_MQ7:
        co_percent = ((raw_value - CLEAN_AIR_MQ7) / (CO_MAX_MQ7 - CLEAN_AIR_MQ7)) * 100
    else:
        co_percent = 0
    return max(0, min(100, co_percent))  # 限制在 0 - 100%


def read_mq9():
    """读取 MQ - 9 天然气浓度（百分比，需校准）"""
    adc = machine.ADC(machine.Pin(MQ9_PIN))
    adc.atten(machine.ADC.ATTN_11DB)
    samples = [adc.read() for _ in range(10)]
    raw_value = sum(samples) // 10

    # 转换为天然气浓度百分比（0 - 100%，实际需根据传感器特性校准）
    if GAS_MAX_MQ9 > CLEAN_AIR_MQ9:
        gas_percent = ((raw_value - CLEAN_AIR_MQ9) / (GAS_MAX_MQ9 - CLEAN_AIR_MQ9)) * 100
    else:
        gas_percent = 0
    return max(0, min(100, gas_percent))  # 限制在 0 - 100%


def generate_sensor_data():
    """整合所有传感器数据"""
    dht_data = read_dht11()
    smoke_percent = read_mq2()
    co_percent = read_mq7()  # 新增 CO 浓度
    gas_percent = read_mq9()  # 新增天然气浓度

    if dht_data and smoke_percent is not None and co_percent is not None and gas_percent is not None:
        return {
            "status": get_status(dht_data["temperature"], smoke_percent, co_percent, gas_percent),
            "co": round(co_percent, 1),       # CO 浓度百分比（替换原虚拟值 0）
            "smoke": round(smoke_percent, 1),  # 烟雾浓度百分比
            "methane": round(gas_percent, 1),      # 天然气浓度百分比
            "temperature": dht_data["temperature"],
            "humidity": dht_data["humidity"]
        }
    return None


def get_status(temperature, smoke_percent, co_percent, gas_percent):
    """根据所有传感器数据判断状态"""
    abnormal_count = 0
    if temperature > TEMPERATURE_THRESHOLD:
        abnormal_count += 1
    if smoke_percent >= SMOKE_THRESHOLD:
        abnormal_count += 1
    if co_percent >= CO_THRESHOLD:
        abnormal_count += 1
    if gas_percent >= GAS_THRESHOLD:
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


def main():
    # 传感器预热（MQ - 2、MQ - 7 和 MQ - 9 均需预热）
    print("传感器预热中...（请保持环境无烟雾、CO 和天然气）")
    time.sleep(10)  # 预热 10 秒

    if not connect_wifi():
        return

    try:
        client = mqtt.MQTTClient(
            client_id=MQTT_CLIENT_ID,
            server=MQTT_BROKER,
            port=MQTT_PORT,
            keepalive=300
        )
        client.connect()
        print(f"已连接到 MQTT 服务器: {MQTT_BROKER}:{MQTT_PORT}")

    except Exception as e:
        print("MQTT 连接失败:", e)
        return

    try:
        while True:
            received_data = uart_read()
            if received_data:
                print(f"接收到数据：{received_data}")
                # 处理数据（示例：回传数据）
                # uart_send(f"已收到：{received_data}\r\n")
                time.sleep(0.1)  # 小延时避免CPU占用过高

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
                time.sleep(5)
                # 判断是否有异常并发送相应数据到串口
                status = sensor_data["status"]
                if status != 1:
                    uart_send("3")

    except KeyboardInterrupt:
        print("\n用户终止程序，正在断开连接...")
        client.disconnect()
    except Exception as e:
        print("主循环错误:", e)
        client.disconnect()


if __name__ == "__main__":
    main()
    