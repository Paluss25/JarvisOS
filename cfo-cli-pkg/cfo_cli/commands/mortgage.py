import click

from cfo_cli.api import client
from cfo_cli.output import render


@click.group(help="Mortgage analysis")
def group() -> None:
    pass


@group.command(name="analyze")
@click.option("--name", "nome", required=True)
@click.option("--bank", "istituto_credito")
@click.option("--rate-type", "tipo_tasso")
@click.option("--principal", "importo_finanziato", required=True, type=float)
@click.option("--remaining-balance", "debito_residuo_attuale", type=float)
@click.option("--tan", required=True, type=float)
@click.option("--taeg", type=float)
@click.option("--spread", type=float)
@click.option("--index", "indice_riferimento")
@click.option("--index-value", "valore_indice_stipula", type=float)
@click.option("--property-value", "valore_immobile", type=float)
@click.option("--purpose", "finalita")
@click.option("--status", "stato")
@click.option("--fees-eur", "spese_accessorie_total_eur", type=float)
@click.option("--duration-months", "durata_mesi", required=True, type=int)
@click.option("--remaining-months", "durata_residua_mesi", type=int)
@click.option("--first-payment-date", "data_prima_rata", required=True)
@click.option("--next-payment-date", "data_prossima_rata")
@click.option("--amortization", "tipo_ammortamento", default="francese", show_default=True)
@click.option("--early-fee-pct", "penale_estinzione_anticipata_pct", type=float)
@click.option("--extra-annual-eur", type=float)
@click.option("--refinance-rate-pct", type=float, hidden=True)
@click.option("--rinegoziazione-rate-pct", type=float)
@click.option("--surroga-rate-pct", type=float)
@click.option("--surroga-duration-months", type=int)
@click.option("--surroga-costs-eur", type=float)
@click.option("--maxi-rate", multiple=True, help="Format month:amount, repeatable")
@click.option("--invest-annual-eur", type=float)
@click.option("--invest-return-pct", type=float)
@click.pass_context
def analyze(
    ctx: click.Context,
    nome: str,
    istituto_credito: str | None,
    tipo_tasso: str | None,
    importo_finanziato: float,
    debito_residuo_attuale: float | None,
    tan: float,
    taeg: float | None,
    spread: float | None,
    indice_riferimento: str | None,
    valore_indice_stipula: float | None,
    valore_immobile: float | None,
    finalita: str | None,
    stato: str | None,
    spese_accessorie_total_eur: float | None,
    durata_mesi: int,
    durata_residua_mesi: int | None,
    data_prima_rata: str,
    data_prossima_rata: str | None,
    tipo_ammortamento: str,
    penale_estinzione_anticipata_pct: float | None,
    extra_annual_eur: float | None,
    refinance_rate_pct: float | None,
    rinegoziazione_rate_pct: float | None,
    surroga_rate_pct: float | None,
    surroga_duration_months: int | None,
    surroga_costs_eur: float | None,
    maxi_rate: tuple[str, ...],
    invest_annual_eur: float | None,
    invest_return_pct: float | None,
) -> None:
    payload: dict[str, object] = {
        "nome": nome,
        "istituto_credito": istituto_credito,
        "tipo_tasso": tipo_tasso,
        "importo_finanziato": importo_finanziato,
        "debito_residuo_attuale": debito_residuo_attuale,
        "tan": tan,
        "taeg": taeg,
        "spread": spread,
        "indice_riferimento": indice_riferimento,
        "valore_indice_stipula": valore_indice_stipula,
        "valore_immobile": valore_immobile,
        "finalita": finalita,
        "stato": stato,
        "spese_accessorie_total_eur": spese_accessorie_total_eur,
        "durata_mesi": durata_mesi,
        "durata_residua_mesi": durata_residua_mesi,
        "data_prima_rata": data_prima_rata,
        "data_prossima_rata": data_prossima_rata,
        "tipo_ammortamento": tipo_ammortamento,
    }
    if penale_estinzione_anticipata_pct is not None:
        payload["penale_estinzione_anticipata_pct"] = penale_estinzione_anticipata_pct

    scenarios: dict[str, object] = {}
    if extra_annual_eur is not None:
        scenarios["extra_payment"] = {"annual_extra_eur": extra_annual_eur}
    if refinance_rate_pct is not None:
        scenarios["refinance"] = {"new_rate_pct": refinance_rate_pct}
    if rinegoziazione_rate_pct is not None:
        scenarios["rinegoziazione"] = {"new_rate_pct": rinegoziazione_rate_pct}
    if surroga_rate_pct is not None:
        surroga_payload: dict[str, object] = {"new_rate_pct": surroga_rate_pct}
        if surroga_duration_months is not None:
            surroga_payload["new_duration_months"] = surroga_duration_months
        if surroga_costs_eur is not None:
            surroga_payload["closing_costs_eur"] = surroga_costs_eur
        scenarios["surroga"] = surroga_payload
    if maxi_rate:
        payments = []
        for raw_item in maxi_rate:
            month_text, amount_text = raw_item.split(":", 1)
            payments.append({"month": int(month_text), "amount_eur": float(amount_text)})
        scenarios["maxi_rate"] = {"payments": payments}
    if invest_annual_eur is not None and invest_return_pct is not None:
        scenarios["invest_instead"] = {
            "annual_contribution_eur": invest_annual_eur,
            "expected_return_pct": invest_return_pct,
        }
    if scenarios:
        payload["scenarios"] = scenarios

    payload = {key: value for key, value in payload.items() if value is not None}
    with client() as api_client:
        response = api_client.post("/mortgage/analyze", json=payload)
    response.raise_for_status()
    render(response.json(), human=ctx.obj.get("human", False))
