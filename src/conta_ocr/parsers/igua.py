"""Parser das contas de água da Iguá Sergipe (foto ou PDF).

Layouts cobertos:
  A) set/out 2026: "Discriminação do faturamento" + "Retenções federais"
  B) nov/2026:     tabela "Serviços" com IBS/CBS + "Outros tributos"

O texto chega já lido pelo OCR, então os padrões são tolerantes e o resultado
é conferido por contas (soma, faixas de tarifa, linha digitável).
"""

import re
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal

from .base import br_date, br_decimal, normalize

CENT = Decimal("0.01")
TOL = Decimal("0.02")
ZERO = Decimal("0.00")

M = r"(\d{1,3}(?:\.\d{3})*,\d{2})"  # dinheiro BR: 1.234,56
RS = r"r\s?[$s§5]"  # "R$" (o OCR às vezes lê "RS" ou "R5")
D = r"(\d{2}/\d{2}/\d{4})"  # dd/mm/aaaa

# Os valores vêm em linhas de "rótulo / valor", então usamos o formato do
# dado (data, data, R$) em vez de depender do rótulo estar colado no valor.
RE_CABECALHO = re.compile(
    r"(?<![\d/])(\d{2}/\d{4})[\s|]+" + D + r"[\s|]+" + RS + r"\s*" + M
)
RE_RODAPE_A = re.compile(RS + r"\s*" + M + r"[\s|]+" + D)
RE_RODAPE_B = re.compile(r"(?<![\d/])" + D + r"[\s|]+(\d{2}/\d{4})(?![\d/])")
RE_LEITURAS = re.compile(r"(?<![\d/])" + D + r"\s+" + D + r"\s+(\d{1,3})\s+" + D)
RE_LINHA_DIGITAVEL = re.compile(r"\s+".join([r"(\d{11})\s?[-–—]\s?\d"] * 4))
RE_FAIXA = re.compile(
    r"(?m)^\W*(\d{1,3})\s+(\d{1,6})\s+(\d{1,3}[.,]\d{4})\s+(\d{1,3}[.,]\d)\b"
)
RE_TRIBUTOS = re.compile(r"(?m)^\W*valor\b\D{0,6}?((?:" + M + r"[ \t]*){3,5})")
RE_ITEM_IBS_CBS = re.compile(
    r"(faturamento agua|faturamento esgoto|multa|juros|correcao)[^\d\n]*(?:\d{2}/\d{4})?\s*"
    + r"\s+".join([M] * 5)
)


def _achar(pattern: str, t: str) -> str | None:
    m = re.search(pattern, t)
    return m.group(1) if m else None


def _valor(rotulo: str, t: str) -> Decimal | None:
    """Primeiro valor em dinheiro depois do rótulo (vale para os dois layouts)."""
    raw = _achar(rotulo + r"[^\d\n]*(?:\d{2}/\d{4})?\s*" + M, t)
    return br_decimal(raw) if raw else None


def _data(s: str | None, nome: str, avisos: list[str]) -> str | None:
    if not s:
        return None
    try:
        return br_date(s)
    except ValueError:
        avisos.append(f"data inválida em {nome}: {s}")
        return None


def _custo_agua(m3: int, faixas: list) -> Decimal:
    """Tarifa progressiva: cada faixa cobra só os m³ que caem nela."""
    total = Decimal(0)
    for ini, fim, tarifa, _ in faixas:
        n = min(m3, fim) - max(ini - 1, 0)
        if n > 0:
            total += n * tarifa
    return total


def _total_da_linha_digitavel(t: str) -> Decimal | None:
    """Convênio de arrecadação: dígitos 5 a 15 do código de barras são o valor."""
    m = RE_LINHA_DIGITAVEL.search(t)
    if not m:
        return None
    d = "".join(m.groups())
    if d[0] != "8" or d[2] not in "67":
        return None
    return Decimal(int(d[4:15])) / 100


def _faixas_ok(f: list) -> bool:
    """Tabela íntegra: começa em 0, faixas contíguas e tarifas crescentes."""
    if len(f) < 3 or f[0][0] != 0:
        return False
    return all(b[0] == a[1] + 1 and b[2] > a[2] for a, b in zip(f, f[1:]))


class IguaParser:
    name = "igua"
    tipo = "agua"

    def matches(self, text: str) -> bool:
        t = normalize(text)
        return bool(re.search(r"\bigua\b", t)) and "sergipe" in t

    def parse(self, text: str) -> tuple[dict, list[str]]:
        t = normalize(text)
        avisos: list[str] = []
        totais: list[Decimal] = []
        ref = emissao = venc = matricula = fatura = None

        # --- identificação, datas e total (cabeçalho, rodapé, código de barras)
        if m := RE_RODAPE_A.search(t):
            totais.append(br_decimal(m[1]))
            emissao = emissao or m[2]
        if m := RE_RODAPE_B.search(t):
            venc, ref = m[1], ref or m[2]
        if (v := _total_da_linha_digitavel(t)) is not None:
            totais.append(v)

        venc = venc or _achar(r"vencimento\D{0,20}" + D, t)
        matricula = _achar(r"(?<![\d-])(\d{7}-\d)(?!\d)", t)
        fatura = _achar(r"(?<!\d)(\d{17})(?!\d)", t)

        total = Counter(totais).most_common(1)[0][0] if totais else None
        if len(set(totais)) > 1:
            avisos.append(
                "total difere entre cabeçalho, rodapé e linha digitável: "
                + ", ".join(str(x) for x in totais)
            )

        leit = RE_LEITURAS.search(t)
        referencia = f"{ref[3:]}-{ref[:2]}" if ref else None
        emissao_iso = _data(emissao, "emissão", avisos)
        venc_iso = _data(venc, "vencimento", avisos)

        # --- medição: 5 números seguidos em que (atual - anterior) == medido
        sec = re.search(r"dados de medic.{0,400}", t, re.S)
        nums = [
            int(n) for n in re.findall(r"(?<!\w)\d{1,6}(?!\w)", sec[0] if sec else t)
        ]
        leit_ant = leit_atual = medido = faturado = medio = None
        for i in range(len(nums) - 4):
            a, b, c, d, e = nums[i : i + 5]
            if b > 0 and b >= a and b - a == c:
                leit_ant, leit_atual, medido, faturado, medio = a, b, c, d, e
                break
        if faturado is None and (m := re.search(r"(?<!\w)(\d{1,4}) ?m3\b", t)):
            faturado = int(m[1])
            avisos.append(
                "dados de medição não encontrados; consumo lido da linha do faturamento"
            )

        # --- faixas de tarifa (R$/m³) e % de esgoto, lidas da própria conta
        faixas = sorted(
            (
                int(a),
                int(b),
                br_decimal(tar.replace(".", ",")),
                br_decimal(pct.replace(".", ",")),
            )
            for a, b, tar, pct in RE_FAIXA.findall(t)
        )
        perc_esgoto = None
        if not _faixas_ok(faixas):
            faixas = []
        if faixas:  # a moda das linhas tolera um dígito errado de OCR
            perc_esgoto = Counter(f[3] for f in faixas).most_common(1)[0][0] / 100

        # --- itens do faturamento
        agua = _valor("faturamento agua", t)
        esgoto = _valor("faturamento esgoto", t)
        multa = _valor("multa", t) or ZERO
        juros = _valor("juros", t) or ZERO
        correcao = _valor("correcao", t) or ZERO

        # --- tributos (informativos, já embutidos no total)
        pis = cofins = None
        if m := RE_TRIBUTOS.search(t):
            v = [br_decimal(x) for x in re.findall(M, m[1])]
            if len(v) in (3, 5):  # 3: PIS COFINS TOTAL | 5: PIS COFINS ISS ICMS TOTAL
                pis, cofins = v[0], v[1]
                if abs(sum(v[:-1]) - v[-1]) > CENT:
                    avisos.append("PIS/COFINS não somam o total de tributos")
        itens = RE_ITEM_IBS_CBS.findall(t)  # só no layout de novembro
        ibs = (
            sum((br_decimal(i[2]) + br_decimal(i[3]) for i in itens), ZERO)
            if itens
            else None
        )
        cbs = sum((br_decimal(i[4]) for i in itens), ZERO) if itens else None

        # --- conferências: qualquer divergência vira aviso (status "revisar")
        for nome, valor in (
            ("mês de referência", ref),
            ("vencimento", venc),
            ("total", total),
            ("faturamento de água", agua),
            ("faturamento de esgoto", esgoto),
            ("consumo", faturado),
        ):
            if valor is None:
                avisos.append(f"campo não encontrado: {nome}")

        if None not in (total, agua, esgoto):
            soma = agua + esgoto + multa + juros + correcao
            if abs(soma - total) > CENT:
                avisos.append(f"itens somam {soma}, mas o total é {total}")

        if faturado is not None and faixas and faixas[-1][1] >= faturado:
            agua_calc = _custo_agua(faturado, faixas)
            if (
                agua is not None
                and abs(agua_calc.quantize(CENT, ROUND_HALF_UP) - agua) > TOL
            ):
                avisos.append(
                    f"água deveria ser {agua_calc:.2f} pelas faixas, mas a conta diz {agua}"
                )
            if esgoto is not None and perc_esgoto is not None:
                esgoto_calc = (agua_calc * perc_esgoto).quantize(CENT, ROUND_HALF_UP)
                if abs(esgoto_calc - esgoto) > TOL:
                    avisos.append(
                        f"esgoto deveria ser {esgoto_calc}, mas a conta diz {esgoto}"
                    )

        if fatura and ref and fatura[-9:-3] != ref.replace("/", ""):
            avisos.append("mês de referência não bate com o nº da fatura")
        if venc_iso and emissao_iso and venc_iso < emissao_iso:
            avisos.append("vencimento anterior à emissão")

        custo_agua_m3 = custo_total_m3 = None
        if faturado:
            if agua is not None:
                custo_agua_m3 = (agua / faturado).quantize(CENT, ROUND_HALF_UP)
                if esgoto is not None:
                    custo_total_m3 = ((agua + esgoto) / faturado).quantize(
                        CENT, ROUND_HALF_UP
                    )

        campos = {
            "referencia": referencia,
            "emissao": emissao_iso,
            "vencimento": venc_iso,
            "matricula": matricula,
            "fatura": fatura,
            "leitura_data_anterior": _data(leit[1], "leitura anterior", avisos)
            if leit
            else None,
            "leitura_data_atual": _data(leit[2], "leitura atual", avisos)
            if leit
            else None,
            "dias_consumo": int(leit[3]) if leit else None,
            "leitura_anterior": leit_ant,
            "leitura_atual": leit_atual,
            "consumo_medido_m3": medido,
            "consumo_faturado_m3": faturado,
            "consumo_medio_m3": medio,
            "agua": agua,
            "esgoto": esgoto,
            "multa": multa,
            "juros": juros,
            "correcao": correcao,
            "total": total,
            "pis": pis,
            "cofins": cofins,
            "ibs": ibs,
            "cbs": cbs,
            "custo_agua_m3": custo_agua_m3,
            "custo_total_m3": custo_total_m3,  # (água + esgoto) / m³ faturado
            "faixas": [
                {"de": a, "ate": b, "tarifa": str(tar), "esgoto_pct": str(pct)}
                for a, b, tar, pct in faixas
            ],
        }
        return {
            k: str(v) if isinstance(v, Decimal) else v for k, v in campos.items()
        }, avisos
