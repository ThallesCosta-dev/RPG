"""Regera os personagens prontos das campanhas com o construtor por classe (habilidades, números derivados).

    python scripts/gerar_pregens.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.cartuchos import Biblioteca  # noqa: E402
from server.fichas import construir_ficha  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
PREGENS = {
    "sombras-de-phandalin": [
        {"id": "pc_bruenor", "nome": "Bruenor", "classe_id": "guerreiro", "nivel": 2, "cor": "#b91c1c", "icone": "🛡️", "voz": "grave",
         "atributos": {"FOR": 3, "DES": 1, "CON": 3, "INT": 0, "SAB": 1, "CAR": -1}, "pericias": ["atletismo", "percepcao", "religiao"],
         "armas": ["machado_de_batalha", "machadinha"], "armadura_id": "cota_de_malha", "escudo": True,
         "historia": "Anão guerreiro de Phandalin, amigo de Gundren Pedrapique."},
        {"id": "pc_lyra", "nome": "Lyra", "classe_id": "ladino", "nivel": 2, "cor": "#15803d", "icone": "🗡️", "voz": "jovem",
         "atributos": {"FOR": 0, "DES": 4, "CON": 1, "INT": 1, "SAB": 0, "CAR": 2}, "pericias": ["furtividade", "acrobacia", "prestidigitacao", "percepcao", "arcanismo"],
         "armas": ["rapieira", "arco_curto", "adaga"], "armadura_id": "couro", "escudo": False,
         "historia": "Meio-elfa criada nas ruas de Neverwinter; batedora do grupo."},
        {"id": "pc_elian", "nome": "Elian", "classe_id": "mago", "nivel": 2, "cor": "#6d28d9", "icone": "🔮", "voz": "masculina",
         "atributos": {"FOR": -1, "DES": 2, "CON": 1, "INT": 4, "SAB": 1, "CAR": 0}, "pericias": ["arcanismo", "historia", "percepcao"],
         "armas": ["bordao", "adaga"], "armadura_id": "nenhuma", "escudo": False,
         "historia": "Aprendiz de Candlekeep em busca de magia perdida."},
        {"id": "pc_mirela", "nome": "Mirela", "classe_id": "clerigo", "nivel": 2, "cor": "#ca8a04", "icone": "✨", "voz": "feminina",
         "atributos": {"FOR": 2, "DES": 0, "CON": 2, "INT": 0, "SAB": 3, "CAR": 1}, "pericias": ["medicina", "religiao", "atletismo"],
         "armas": ["maca"], "armadura_id": "cota_de_escamas", "escudo": True,
         "historia": "Clériga da Vida devota de Lathander."},
    ],
    "coracao-de-rubi": [
        {"id": "player_thorin", "nome": "Thorin", "classe_id": "guerreiro", "nivel": 3, "cor": "#c0392b", "icone": "🪓", "voz": "grave",
         "atributos": {"FOR": 4, "DES": 1, "CON": 3, "INT": 0, "SAB": 1, "CAR": -1}, "pericias": ["atletismo", "percepcao", "diplomacia"],
         "armas": ["machado_de_batalha", "machadinha"], "armadura_id": "cota_de_malha", "escudo": True},
        {"id": "player_lia", "nome": "Lia", "classe_id": "cacador", "nivel": 3, "cor": "#27ae60", "icone": "🏹", "voz": "jovem",
         "atributos": {"FOR": 1, "DES": 4, "CON": 1, "INT": 0, "SAB": 2, "CAR": 0}, "pericias": ["pontaria", "furtividade", "percepcao", "acrobacia", "iniciativa"],
         "armas": ["arco_longo", "espada_curta"], "armadura_id": "couro_batido", "escudo": False},
        {"id": "player_maya", "nome": "Maya", "classe_id": "arcanista", "nivel": 3, "cor": "#8e44ad", "icone": "🔮", "voz": "feminina",
         "atributos": {"FOR": -1, "DES": 2, "CON": 1, "INT": 4, "SAB": 1, "CAR": 1}, "pericias": ["conhecimento", "investigacao", "atletismo"],
         "armas": ["bordao", "adaga"], "armadura_id": "nenhuma", "escudo": False},
        {"id": "player_bruno", "nome": "Bruno", "classe_id": "clerigo", "nivel": 3, "cor": "#f39c12", "icone": "✨", "voz": "masculina",
         "atributos": {"FOR": 2, "DES": 0, "CON": 2, "INT": 0, "SAB": 4, "CAR": 1}, "pericias": ["cura", "diplomacia", "acrobacia"],
         "armas": ["maca"], "armadura_id": "cota_de_malha", "escudo": True},
    ],
}


def main() -> int:
    bib = Biblioteca(RAIZ / "cartuchos")
    for camp_id, lista in PREGENS.items():
        camp = bib.campanha(camp_id)
        sis = bib.sistema(camp.sistema_id)
        saida = {}
        for pre in lista:
            ficha, erros = construir_ficha(pre, sis, None)
            if erros:
                print(f"  ERRO {pre['nome']}: {erros}")
                return 1
            ficha["id"] = pre["id"]                                   # id estável para as campanhas/testes
            ficha["personalizada"] = False
            ficha["voz"] = pre.get("voz")
            saida[ficha["id"]] = ficha
            print(f"  {camp_id:<22} {ficha['nome']:<8} {ficha['classe']:<22} PV {ficha['barras']['pv']['max']:>3}  Def {ficha['defesa']:>2}  "
                  f"ataques {[(a['id'], a['bonus'], a['dano']) for a in ficha['ataques'][:2]]}  habilidades {[h['id'] for h in ficha['habilidades']]}")
        destino = camp.caminho / "compilado" / "personagens.json"
        destino.write_text(json.dumps(saida, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
