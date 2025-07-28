import asyncio
import os
from bleak import BleakScanner, BleakClient

NUS_TX_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
NUS_RX_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
LAST_DEVICE_FILE = "last_device.txt"
COMS_FILE = "coms.txt"

client = None
reconnecting = False
reconnect_event = asyncio.Event()


def clear_console():
    os.system('cls' if os.name == 'nt' else 'clear')


def handle_rx(_, data: bytearray):
    if len(data) == 3:
        cmd, a, b = data[0], data[1], data[2]
        print(f"📥 Evt={cmd}, A={a}, B={b}")
    else:
        try:
            print(f"📥 Texto: {data.decode('utf-8').strip()}")
        except UnicodeDecodeError:
            print(f"📥 Binario (hex): {data.hex()}")


def on_disconnect(c):
    global reconnecting
    if not reconnecting:
        reconnecting = True
        reconnect_event.clear()
        print("⚠️ Se ha desconectado.")
        asyncio.create_task(handle_reconnection())


async def scan_and_select_device():
    while True:
        clear_console()
        print("🔍 Escaneando BLE...")
        devices = await BleakScanner.discover(timeout=3.0)
        if not devices:
            print("❌ No se detectaron dispositivos.")
            if input("¿Intentar de nuevo? (s/N): ").lower() == 's':
                continue
            return None

        print("[0] Volver a escanear")
        for idx, d in enumerate(devices, start=1):
            print(f"[{idx}] {d.name or 'Sin nombre'} – {d.address}")

        try:
            choice = int(input("Selecciona opción: "))
        except ValueError:
            print("❌ Entrada inválida.")
            continue

        if choice == 0:
            continue
        if 1 <= choice <= len(devices):
            addr = devices[choice - 1].address
            with open(LAST_DEVICE_FILE, "w") as f:
                f.write(addr)
            return addr

        print("❌ Opción inválida. Intenta de nuevo.")


def load_commands():
    commands = {}
    if os.path.exists(COMS_FILE):
        with open(COMS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or ':' not in line:
                    continue
                cmd, desc = line.split(':', 1)
                commands[cmd.strip()] = desc.strip()
    return commands


async def connect_to_device(address):
    global client
    client = BleakClient(address, disconnected_callback=on_disconnect)
    try:
        await client.connect()
        if client.is_connected:
            print("✅ Conectado.")
            await client.start_notify(NUS_RX_UUID, handle_rx)
            return True
        else:
            print("❌ No se pudo conectar.")
    except Exception as e:
        print(f"❌ Error al conectar: {e}")
    return False


async def handle_reconnection():
    global reconnecting, reconnect_event
    print("🔄 Intentando reconexión...")
    while True:
        await asyncio.sleep(2)
        try:
            if client:
                await client.connect()
                if client.is_connected:
                    print("✅ Reconectado.")
                    await client.start_notify(NUS_RX_UUID, handle_rx)
                    reconnecting = False
                    reconnect_event.set()
                    break
        except Exception as e:
            print(f"⏳ Reintentando... {e}")


async def command_loop():
    global client, reconnect_event
    while True:
        try:
            inp = input("➡️ ").strip()
            low = inp.lower()

            if low == 'clc':
                clear_console()
                continue

            # comando rápido: com <índice>
            if low.startswith("com ") and low[4:].isdigit():
                idx = int(low[4:])
                cmds = load_commands()
                items = list(cmds.items())
                if 0 <= idx < len(items):
                    selected_cmd = items[idx][0]
                    # prefill prompt: muestra comando y permite añadir texto
                    suffix = input(f"➡️ {selected_cmd} ")
                    send = f"{selected_cmd}{(' ' + suffix) if suffix.strip() else ''}"
                    print(f"🚀 Enviando: {send}")
                    if client and client.is_connected:
                        await client.write_gatt_char(NUS_TX_UUID, send.encode())
                    else:
                        print("⌛ No conectado, esperando reconexión...")
                        await reconnect_event.wait()
                        await client.write_gatt_char(NUS_TX_UUID, send.encode())
                else:
                    print("❌ Índice fuera de rango.")
                continue

            if low == "com":
                cmds = load_commands()
                if not cmds:
                    print(f"❌ No hay comandos en {COMS_FILE}")
                    continue
                print("📋 Comandos disponibles:")
                for i, (c, d) in enumerate(cmds.items()):
                    print(f"[{i}] {c}: {d}")
                continue

            if low in ("exit", "quit"):
                print("↩️ Volviendo al escaneo de dispositivos...")
                return True

            if client and client.is_connected:
                try:
                    await client.write_gatt_char(NUS_TX_UUID, inp.encode())
                except OSError as e:
                    print(f"⛔ Error al enviar: {e}")
                    print("⌛ Esperando reconexión...")
                    await reconnect_event.wait()
                    print("✅ Reconexión lista. Intenta de nuevo.")
            else:
                print("⌛ Esperando reconexión...")
                await reconnect_event.wait()
        except KeyboardInterrupt:
            return False


async def main():
    while True:
        clear_console()
        address = None
        if os.path.exists(LAST_DEVICE_FILE):
            last = open(LAST_DEVICE_FILE).read().strip()
            print(f"🔁 Último dispositivo: {last}")
            if input("¿Usar este dispositivo? (S/n): ").lower() == 'n':
                address = await scan_and_select_device()

        if not address:
                address = last
        if not address:
            break
        if not await connect_to_device(address):
            input("Presiona Enter para reintentar...")
            continue
        back_to_scan = await command_loop()
        if client and client.is_connected:
            await client.stop_notify(NUS_RX_UUID)
            await client.disconnect()
        if not back_to_scan:
            break
    print("🔌 Programa terminado.")


if __name__ == "__main__":
    asyncio.run(main())