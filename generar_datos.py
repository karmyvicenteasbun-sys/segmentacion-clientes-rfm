"""
Genera los datos ficticios de una distribuidora de bebidas con unos 1.200
clientes (tiendas de barrio, kioscos, minimercados, restaurantes y mayoristas)
entre octubre de 2024 y septiembre de 2026, con montos en bolivianos (Bs).

Salidas (carpeta datos/):
  - clientes.csv  una fila por cliente
  - ventas.csv    una fila por pedido

Todo es inventado: no hay datos de ninguna empresa real. Los datos no dicen
qué clientes dejaron de comprar: eso es lo que el análisis tiene que descubrir.

Uso:
    python generar_datos.py
"""

from pathlib import Path

import numpy as np
import pandas as pd

SEMILLA = 2026
INICIO = pd.Period("2024-10", freq="M")
FIN = pd.Period("2026-09", freq="M")
CLIENTES_INICIALES = 1150
ALTAS_POR_MES = 26

# peso: participación en la cartera | pedidos: pedidos por mes | cajas: cajas por pedido
# precio: Bs por caja | abandono: probabilidad mensual de dejar de comprar
TIPOS = {
    "Tienda de barrio":      dict(peso=0.48, pedidos=3.2, cajas=7.0, precio=60, abandono=0.017),
    "Kiosco":                dict(peso=0.17, pedidos=2.4, cajas=3.5, precio=62, abandono=0.024),
    "Minimercado":           dict(peso=0.15, pedidos=3.8, cajas=24.0, precio=57, abandono=0.011),
    "Restaurante o pensión": dict(peso=0.14, pedidos=2.8, cajas=12.0, precio=60, abandono=0.019),
    "Mayorista":             dict(peso=0.06, pedidos=5.0, cajas=80.0, precio=52, abandono=0.007),
}

# Rutas de preventa por zona. En tres rutas los clientes abandonan más del doble:
# el análisis tiene que encontrarlas sin saberlo de antemano.
ZONAS = {"Norte": 6, "Sur": 5, "Este": 5, "Oeste": 4, "Centro": 4}
RUTAS_CON_PROBLEMAS = {"R07": 2.3, "R15": 2.3, "R21": 2.3}

# Temporada alta de bebidas: verano y fin de año
ESTACIONALIDAD = {1: 1.25, 2: 1.20, 3: 1.05, 4: 0.95, 5: 0.90, 6: 0.82,
                  7: 0.80, 8: 0.85, 9: 0.95, 10: 1.05, 11: 1.15, 12: 1.35}

# Antes de irse, el cliente compra menos durante unos meses
MESES_DE_CAIDA = (2, 3, 4)
CAIDA_PEDIDOS = 0.45
CAIDA_CAJAS = 0.80


def asignar_rutas():
    rutas, numero = {}, 1
    for zona, cantidad in ZONAS.items():
        for _ in range(cantidad):
            rutas[f"R{numero:02d}"] = zona
            numero += 1
    return rutas


class Distribuidora:
    def __init__(self, semilla=SEMILLA):
        self.rng = np.random.default_rng(semilla)
        self.rutas = asignar_rutas()
        self.clientes = []
        self.pedidos = []

    def nuevo_cliente(self, fecha_alta):
        rng = self.rng
        tipos = list(TIPOS)
        tipo = tipos[rng.choice(len(tipos), p=[TIPOS[t]["peso"] for t in tipos])]
        ruta = rng.choice(list(self.rutas))
        cliente = dict(
            id_cliente=f"C{len(self.clientes) + 1:04d}",
            tipo=tipo,
            zona=self.rutas[ruta],
            ruta=ruta,
            fecha_alta=fecha_alta,
            escala_pedidos=float(rng.lognormal(0, 0.35)),
            escala_cajas=float(rng.lognormal(0, 0.50)),
            fragilidad=float(rng.lognormal(-0.08, 0.40)),
            meses_de_caida=None,   # None: compra normal | n > 0: en caída | 0: ya no compra
        )
        self.clientes.append(cliente)
        return cliente

    def poblacion_inicial(self):
        inicio = INICIO.to_timestamp()
        for _ in range(CLIENTES_INICIALES):
            antiguedad_dias = int(self.rng.exponential(3 * 365)) + 1
            self.nuevo_cliente(inicio - pd.Timedelta(days=antiguedad_dias))

    def dias_de_visita(self, periodo, cantidad, desde=None):
        """Días hábiles (lunes a sábado) del mes elegidos al azar."""
        dias = pd.date_range(periodo.start_time, periodo.end_time.normalize(), freq="D")
        dias = dias[dias.dayofweek < 6]
        if desde is not None:
            dias = dias[dias >= desde]
        if len(dias) == 0 or cantidad == 0:
            return []
        return sorted(self.rng.choice(dias, size=cantidad, replace=True))

    def simular(self):
        rng = self.rng
        self.poblacion_inicial()
        for periodo in pd.period_range(INICIO, FIN, freq="M"):
            # altas del mes
            for _ in range(rng.poisson(ALTAS_POR_MES)):
                dia = rng.integers(1, periodo.days_in_month + 1)
                self.nuevo_cliente(pd.Timestamp(periodo.year, periodo.month, dia))
            temporada = ESTACIONALIDAD[periodo.month]
            for c in self.clientes:
                if c["meses_de_caida"] == 0 or c["fecha_alta"] > periodo.end_time:
                    continue
                t = TIPOS[c["tipo"]]
                # ¿decide dejar de comprar este mes?
                if c["meses_de_caida"] is None:
                    meses_antiguedad = (periodo.start_time - c["fecha_alta"]).days / 30
                    # quien compra más seguido depende más de la distribuidora y se va menos
                    riesgo = (t["abandono"] * c["fragilidad"] * c["escala_pedidos"] ** -0.8
                              * RUTAS_CON_PROBLEMAS.get(c["ruta"], 1.0) * (1.5 if meses_antiguedad < 6 else 1.0))
                    if rng.random() < riesgo:
                        c["meses_de_caida"] = int(rng.choice(MESES_DE_CAIDA))
                en_caida = c["meses_de_caida"] is not None
                pedidos_mes = t["pedidos"] * c["escala_pedidos"] * np.sqrt(temporada) * (CAIDA_PEDIDOS if en_caida else 1)
                desde = c["fecha_alta"] if c["fecha_alta"] >= periodo.start_time else None
                for fecha in self.dias_de_visita(periodo, rng.poisson(pedidos_mes), desde):
                    cajas_medias = t["cajas"] * c["escala_cajas"] * np.sqrt(temporada) * (CAIDA_CAJAS if en_caida else 1)
                    cajas = max(1, int(round(cajas_medias * rng.lognormal(-0.06, 0.35))))
                    self.pedidos.append((fecha, c["id_cliente"], cajas, round(cajas * t["precio"], 2)))
                if en_caida:
                    c["meses_de_caida"] -= 1
        return self

    def tabla_clientes(self):
        df = pd.DataFrame(self.clientes)
        df["fecha_alta"] = pd.to_datetime(df["fecha_alta"]).dt.date
        return df[["id_cliente", "tipo", "zona", "ruta", "fecha_alta"]]

    def tabla_ventas(self):
        df = pd.DataFrame(self.pedidos, columns=["fecha", "id_cliente", "cajas", "monto_bs"])
        df = df.sort_values(["fecha", "id_cliente"], kind="stable").reset_index(drop=True)
        df.insert(0, "id_pedido", [f"P{i:06d}" for i in range(1, len(df) + 1)])
        df["fecha"] = pd.to_datetime(df["fecha"]).dt.date
        return df


def main():
    carpeta = Path(__file__).resolve().parent / "datos"
    carpeta.mkdir(exist_ok=True)
    distribuidora = Distribuidora().simular()
    clientes = distribuidora.tabla_clientes()
    ventas = distribuidora.tabla_ventas()
    # Solo quedan los clientes con al menos un pedido en el período
    clientes = clientes[clientes["id_cliente"].isin(ventas["id_cliente"])]
    clientes.to_csv(carpeta / "clientes.csv", index=False, encoding="utf-8")
    ventas.to_csv(carpeta / "ventas.csv", index=False, encoding="utf-8")
    print(f"clientes.csv: {len(clientes):,} filas")
    print(f"ventas.csv: {len(ventas):,} filas")


if __name__ == "__main__":
    main()
