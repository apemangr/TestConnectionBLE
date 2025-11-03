import asyncio
import os
import csv
from datetime import datetime
from bleak import BleakScanner, BleakClient

NUS_TX_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
NUS_RX_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
LAST_DEVICE_FILE = "last_device.txt"
COMS_FILE = "coms.txt"
LOG_FILE = "received_data.txt"

client = None
reconnecting = False
reconnect_event = asyncio.Event()

# Set para evitar guardar RAW duplicados
seen_hex = set()

def clear_console():
    os.system('cls' if os.name == 'nt' else 'clear')

def interpret_adv_history(hex_string):
    """
    Interpreta historial ADV (empieza con 0xAD)
    Formato: 17 bytes
    Byte 0: 0xAD (prefijo)
    Bytes 1-7: Fecha/hora
    Bytes 8-11: Contador
    Bytes 12-15: V1, V2
    Byte 16: 0xFF (marcador de fin)
    """
    try:
        data = bytes.fromhex(hex_string)
        
        # Verificar longitud mínima y magic byte
        if len(data) < 17:
            return None
        if data[0] != 0xAD:
            return None
        
        result = {}
        result['type'] = 'ADV_HISTORY'
        
        # Fecha y hora (bytes 1-7)
        result['day'] = data[1]
        result['month'] = data[2]
        result['year'] = (data[3] << 8) | data[4]
        result['hour'] = data[5]
        result['minute'] = data[6]
        result['second'] = data[7]
        
        # Contador (bytes 8-11, big-endian)
        result['contador'] = (data[8] << 24) | (data[9] << 16) | (data[10] << 8) | data[11]
        
        # V1, V2 (bytes 12-15, big-endian)
        result['V1'] = (data[12] << 8) | data[13]
        result['V2'] = (data[14] << 8) | data[15]
        
        # Verificar marcador de fin
        if data[16] == 0xFF:
            result['end_marker'] = 'OK'
        else:
            result['end_marker'] = 'INVALID'
        
        return result
        
    except Exception:
        return None


def interpret_binary_data(hex_string):
    """
    Interpreta los datos binarios según el formato especificado
    """
    try:
        data = bytes.fromhex(hex_string)
        if len(data) < 44:
            return None
        if data[0] != 0x98 and data[0] != 0x08:
            return None

        result = {}
        result['type'] = 'STANDARD'
        result['day'] = data[1]
        result['month'] = data[2]
        result['year'] = (data[3] << 8) | data[4]
        result['hour'] = data[5]
        result['minute'] = data[6]
        result['second'] = data[7]
        result['contador'] = (data[8] << 24) | (data[9] << 16) | (data[10] << 8) | data[11]
        result['V1'] = (data[12] << 8) | data[13]
        result['V2'] = (data[14] << 8) | data[15]
        result['battery'] = data[16]
        result['V3'] = (data[29] << 8) | data[30]
        result['V4'] = (data[31] << 8) | data[32]
        result['V5'] = (data[33] << 8) | data[34]
        result['V6'] = (data[35] << 8) | data[36]
        result['V7'] = (data[37] << 8) | data[38]
        result['V8'] = (data[39] << 8) | data[40]
        result['temp'] = data[41]
        result['last_pos'] = (data[42] << 8) | data[43]
        return result
    except Exception:
        return None

def format_interpreted_data(data):
    if not data:
        return "❌ Datos no válidos"
    
    fecha = f"{data['day']:02d}/{data['month']:02d}/{data['year']}"
    hora = f"{data['hour']:02d}:{data['minute']:02d}:{data['second']:02d}"
    
    # Verificar si es historial ADV
    if data.get('type') == 'ADV_HISTORY':
        end_status = "✅" if data.get('end_marker') == 'OK' else "❌"
        return (f"📜 [HISTORIAL ADV] {fecha} {hora} | "
                f"Cnt:{data['contador']} | V1:{data['V1']} V2:{data['V2']} | "
                f"End:{end_status}")
    
    # Formato estándar
    return (f"📊 {fecha} {hora} | Cnt:{data['contador']} | "
            f"V1:{data['V1']} V2:{data['V2']} V3:{data['V3']} V4:{data['V4']} "
            f"V5:{data['V5']} V6:{data['V6']} V7:{data['V7']} V8:{data['V8']} | "
            f"Bat:{data['battery']} Temp:{data['temp']}°C")

def generate_csv_from_log(log_file, csv_file):
    try:
        interpreted_data = []
        if not os.path.exists(log_file):
            return 0, "No existe el archivo de log"
        with open(log_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for line in lines:
            line = line.strip()
            if "Binario (hex):" in line:
                parts = line.split(" - Binario (hex): ")
                if len(parts) == 2:
                    timestamp = parts[0]
                    hex_data = parts[1]
                    
                    # Intentar interpretar como historial ADV primero
                    interpreted = interpret_adv_history(hex_data)
                    
                    # Si no es ADV, intentar formato estándar
                    if not interpreted:
                        interpreted = interpret_binary_data(hex_data)
                    
                    if interpreted:
                        fecha = f"{interpreted['day']:02d}/{interpreted['month']:02d}/{interpreted['year']}"
                        hora = f"{interpreted['hour']:02d}:{interpreted['minute']:02d}:{interpreted['second']:02d}"
                        fecha_hora = f"{fecha} {hora}"
                        mac = "N/A"
                        
                        # Para historial ADV, batería es N/A
                        bateria = interpreted.get('battery', 'N/A')
                        
                        interpreted_data.append({
                            'Fecha': fecha_hora,
                            'Equipo(MAC)': mac,
                            'Counter': interpreted['contador'],
                            'V1': interpreted['V1'],
                            'V2': interpreted['V2'],
                            'Bateria': bateria
                        })
        if interpreted_data:
            with open(csv_file, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = ['Fecha', 'Equipo(MAC)', 'Counter', 'V1', 'V2', 'Bateria']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                for row in interpreted_data:
                    writer.writerow(row)
            return len(interpreted_data), None
        else:
            return 0, "No se encontraron datos interpretables"
    except Exception as e:
        return 0, f"Error al generar CSV: {e}"

def handle_rx(_, data: bytearray):
    global seen_hex
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    to_write = True
    
    # Siempre mostrar el raw hex primero
    hex_data = data.hex()
    print(f"📥 Raw hex: {hex_data}")

    if len(data) == 3:
        cmd, a, b = data[0], data[1], data[2]
        message = f"Evt={cmd}, A={a}, B={b}"
        print(f"   └─ {message}")
        log_entry = f"{timestamp} - {message}\n"
    else:
        try:
            decoded_text = data.decode('utf-8').strip()
            print(f"   └─ Texto: {decoded_text}")
            log_entry = f"{timestamp} - Texto: {decoded_text}\n"
        except UnicodeDecodeError:
            if hex_data in seen_hex:
                to_write = False
            else:
                seen_hex.add(hex_data)
            
            # Intentar interpretar como historial ADV primero
            interpreted = interpret_adv_history(hex_data)
            
            # Si no es ADV, intentar formato estándar
            if not interpreted:
                interpreted = interpret_binary_data(hex_data)
            
            if interpreted:
                formatted = format_interpreted_data(interpreted)
                print(f"   └─ {formatted}")
            else:
                print(f"   └─ Binario sin interpretar")
            
            log_entry = f"{timestamp} - Binario (hex): {hex_data}\n"

    if to_write:
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(log_entry)
        except Exception as e:
            print(f"⚠️ Error al guardar en log: {e}")

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
    print("💡 Comandos especiales: 'com', 'log', 'interplog', 'clearlog', 'clc', 'exit/quit'")
    while True:
        try:
            inp = input("➡️ ").strip()
            low = inp.lower()

            if low == 'clc':
                clear_console()
                continue

            if low == 'log':
                if os.path.exists(LOG_FILE):
                    with open(LOG_FILE, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                    print(f"📄 Archivo de log: {LOG_FILE}")
                    print(f"📊 Total de líneas: {len(lines)}")
                    if lines:
                        print("🕒 Últimas 5 entradas:")
                        for line in lines[-5:]:
                            print(f"   {line.strip()}")
                else:
                    print(f"📄 No existe el archivo de log: {LOG_FILE}")
                continue

            if low == 'interplog':
                if os.path.exists(LOG_FILE):
                    csv_filename = f"datos_interpretados_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
                    count, error = generate_csv_from_log(LOG_FILE, csv_filename)
                    if error:
                        print(f"❌ Error: {error}")
                        continue
                    print(f"📊 CSV generado: {csv_filename}")
                    print(f"✅ Registros exportados: {count}")
                    
                    with open(LOG_FILE, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                    print(f"\n🔍 Interpretando log: {LOG_FILE}")
                    print(f"📊 Total de líneas: {len(lines)}")
                    print("=" * 120)
                    interpreted_count = 0
                    for line in lines:
                        line = line.strip()
                        if "Binario (hex):" in line:
                            parts = line.split(" - Binario (hex): ")
                            if len(parts) == 2:
                                timestamp = parts[0]
                                hex_data = parts[1]
                                
                                # Intentar interpretar como historial ADV primero
                                interpreted = interpret_adv_history(hex_data)
                                
                                # Si no es ADV, intentar formato estándar
                                if not interpreted:
                                    interpreted = interpret_binary_data(hex_data)
                                
                                if interpreted:
                                    formatted = format_interpreted_data(interpreted)
                                    print(f"{timestamp} | {formatted}")
                                    interpreted_count += 1
                                else:
                                    print(f"{timestamp} | ❌ Datos no interpretables: {hex_data}")
                        elif "Texto:" in line or "Evt=" in line:
                            print(f"{line}")
                    print("=" * 120)
                    print(f"✅ Registros interpretados: {interpreted_count}")
                else:
                    print(f"📄 No existe el archivo de log: {LOG_FILE}")
                continue

            if low == 'clearlog':
                if os.path.exists(LOG_FILE):
                    os.remove(LOG_FILE)
                    print(f"🗑️ Archivo de log eliminado: {LOG_FILE}")
                    seen_hex.clear()  # Limpiar set de duplicados
                else:
                    print(f"📄 No existe el archivo de log: {LOG_FILE}")
                continue

            if low.startswith("com ") and low[4:].isdigit():
                idx = int(low[4:])
                cmds = load_commands()
                items = list(cmds.items())
                if 0 <= idx < len(items):
                    selected_cmd = items[idx][0]
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

