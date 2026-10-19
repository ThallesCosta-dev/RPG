"""Carregamento de cartuchos compilados (somente leitura em tempo de jogo) — §4, §5.

Um cartucho de sistema = system_config.json + efeitos.json + monstros.json (+ plugin.py opcional).
Um cartucho de campanha = manifest.json + personagens.json + npcs.json + cenas.json (+ mapas prontos).
"""
from __future__ import annotations

import copy
import importlib.util
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .grid_math import validar_tilemap


def _ler_json(caminho: Path, padrao: Any = None) -> Any:
    if not caminho.exists():
        if padrao is not None:
            return padrao
        raise FileNotFoundError(caminho)
    return json.loads(caminho.read_text(encoding="utf-8"))


@dataclass
class Sistema:
    id: str
    nome: str
    manifest: dict
    config: dict
    efeitos: dict
    monstros: dict
    plugin: Any = None
    caminho: Path | None = None
    classes: dict = field(default_factory=dict)

    @property
    def revisado(self) -> bool:
        return self.manifest.get("status") == "revisado"


@dataclass
class Campanha:
    id: str
    nome: str
    manifest: dict
    personagens: dict          # personagens jogáveis (modelos)
    npcs: dict                 # modelos de NPC por id
    cenas: dict                # cenas já expandidas (npcs instanciados com posição)
    caminho: Path | None = None
    texto_fonte: str = ""

    @property
    def tema(self) -> str:
        return self.manifest.get("tema", "medieval")

    @property
    def sistema_id(self) -> str:
        return self.manifest["sistema_id"]

    @property
    def cena_inicial(self) -> str:
        return self.manifest.get("cena_inicial") or next(iter(self.cenas))

    @property
    def revisado(self) -> bool:
        return self.manifest.get("status") == "revisado"


def _expandir_cenas(cenas: dict, npcs: dict, tema: str, caminho: Path | None) -> dict:
    """`npcs: ["boss_orc@6,4"]` → lista de fichas completas com x, y. Valida os tilemaps."""
    out = {}
    for cid, cena in cenas.items():
        cena = copy.deepcopy(cena)
        cena.setdefault("id", cid)
        erros = validar_tilemap(cena["tilemap"])
        if erros:
            raise ValueError(f"cena {cid}: " + "; ".join(erros[:5]))
        cena.setdefault("tema", tema)
        instancias = []
        for i, ref in enumerate(cena.get("npcs", [])):
            if isinstance(ref, dict):
                instancias.append(ref)
                continue
            nid, _, pos = ref.partition("@")
            if nid not in npcs:
                raise ValueError(f"cena {cid}: NPC desconhecido {nid}")
            ficha = copy.deepcopy(npcs[nid])
            ficha["id"] = nid
            if pos:
                x, y = pos.split(",")
                ficha["x"], ficha["y"] = int(x), int(y)
            else:
                ficha["x"], ficha["y"] = cena.get("entrada", [1, 1])
            ficha.setdefault("tipo", "npc")
            ficha.setdefault("condicoes", [])
            ficha.setdefault("caido", False)
            instancias.append(ficha)
        cena["npcs"] = instancias
        if cena.get("imagem") and caminho:
            cena["imagem_url"] = f"/cartuchos/campanhas/{caminho.name}/mapas/{cena['imagem']}"
        else:
            cena.setdefault("imagem_url", None)
        out[cid] = cena
    return out


class Biblioteca:
    def __init__(self, raiz: str | Path = "cartuchos"):
        self.raiz = Path(raiz)
        self._sistemas: dict[str, Sistema] = {}
        self._campanhas: dict[str, Campanha] = {}

    # ---------------------------------------------------------------- listagem
    def listar_sistemas(self) -> list[dict]:
        out = []
        for d in sorted((self.raiz / "sistemas").glob("*/")):
            m = _ler_json(d / "manifest.json", {})
            if m:
                out.append({"id": m.get("id", d.name), "nome": m.get("nome", d.name),
                            "revisado": m.get("status") == "revisado"})
        return out

    def listar_campanhas(self) -> list[dict]:
        out = []
        for d in sorted((self.raiz / "campanhas").glob("*/")):
            m = _ler_json(d / "manifest.json", {})
            if m:
                out.append({"id": m.get("id", d.name), "nome": m.get("nome", d.name), "tema": m.get("tema", "medieval"),
                            "sistema_id": m.get("sistema_id"), "revisado": m.get("status") == "revisado",
                            "descricao": m.get("descricao", "")})
        return out

    # ---------------------------------------------------------------- carga
    def sistema(self, sistema_id: str) -> Sistema:
        if sistema_id in self._sistemas:
            return self._sistemas[sistema_id]
        d = self.raiz / "sistemas" / sistema_id
        if not d.exists():
            raise KeyError(f"sistema desconhecido: {sistema_id}")
        manifest = _ler_json(d / "manifest.json", {"id": sistema_id, "nome": sistema_id})
        comp = d / "compilado"
        config = _ler_json(comp / "system_config.json")
        efeitos = _ler_json(comp / "efeitos.json", {"nenhum": {}})
        monstros = _ler_json(comp / "monstros.json", {})
        classes = _ler_json(comp / "classes.json", {})
        plugin = None
        if (d / "plugin.py").exists():
            spec = importlib.util.spec_from_file_location(f"plugin_{sistema_id}", d / "plugin.py")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)                       # type: ignore[union-attr]
            plugin = getattr(mod, "Plugin", None)
            plugin = plugin() if plugin else mod
        s = Sistema(sistema_id, manifest.get("nome", sistema_id), manifest, config, efeitos, monstros, plugin, d, classes)
        self._sistemas[sistema_id] = s
        return s

    def campanha(self, campanha_id: str) -> Campanha:
        if campanha_id in self._campanhas:
            return self._campanhas[campanha_id]
        d = self.raiz / "campanhas" / campanha_id
        if not d.exists():
            raise KeyError(f"campanha desconhecida: {campanha_id}")
        manifest = _ler_json(d / "manifest.json")
        comp = d / "compilado"
        personagens = _ler_json(comp / "personagens.json", {})
        npcs = _ler_json(comp / "npcs.json", {})
        cenas = _expandir_cenas(_ler_json(comp / "cenas.json"), npcs, manifest.get("tema", "medieval"), d)
        texto = ""
        fonte = d / manifest.get("fonte", "campanha.md")
        if fonte.exists():
            texto = fonte.read_text(encoding="utf-8")
        c = Campanha(campanha_id, manifest.get("nome", campanha_id), manifest, personagens, npcs, cenas, d, texto)
        self._campanhas[campanha_id] = c
        return c

    def invalidar(self) -> None:
        self._sistemas.clear()
        self._campanhas.clear()


def montar_cena_inicial(campanha: Campanha, cena_id: str | None = None) -> dict:
    """Cena no formato do estado (§1 do contrato), sem personagens posicionados ainda."""
    cena = campanha.cenas[cena_id or campanha.cena_inicial]
    return {"id": cena["id"], "nome": cena["nome"], "descricao": cena.get("descricao", ""), "tema": cena.get("tema", campanha.tema),
            "tilemap": cena["tilemap"], "largura": len(cena["tilemap"][0]), "altura": len(cena["tilemap"]),
            "imagem_url": cena.get("imagem_url")}
