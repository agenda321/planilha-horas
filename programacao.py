import re
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy

# Importa o db do app principal
# No app.py, registre assim:
#   from programacao import programacao_bp
#   app.register_blueprint(programacao_bp)

programacao_bp = Blueprint("programacao", __name__)

# db será injetado pelo app principal via init_app
# Para funcionar, importe e use o mesmo db do app.py
db = None  # será substituído em init_programacao(db_instance)

def init_programacao(db_instance):
    global db
    db = db_instance

# ===== MODELS =====

class ProgramacaoDia(db.Model if False else object):
    pass

# Os models são definidos dinamicamente após init
_models_created = False

def get_models():
    """Retorna os models após o db ter sido injetado."""
    return VooDia, MembroTripulacao

# Vamos usar uma abordagem diferente: definir os models no app.py
# e importar aqui. Por simplicidade, definimos as queries via db diretamente.

# ===== PARSER DO TEXTO DO WHATSAPP =====

def parse_programacao(texto: str, data_str: str) -> dict:
    """
    Faz o parse do texto recebido pelo WhatsApp e retorna
    uma estrutura de dados organizada por aeronave e cliente.
    
    Formato esperado:
        Tipo - Número OMA (ou apenas Tipo sem OMA)
        Matrícula Piloto(/Copiloto)
        Rota (separada por / ou ›)
        Obs: texto
    """
    linhas = [l.strip() for l in texto.strip().splitlines()]
    linhas = [l for l in linhas if l]  # remove vazias

    resultado = {
        "data": data_str,
        "aeronaves": {},       # { "CARAVAN": { "Voare": [...], "Leste": [...], "Yanomami": [...] } }
        "stand_by": [],
        "folga_regular": [],
        "coordenacao": [],
        "stand_by_voare": [],
        "erros": []            # linhas que não foram reconhecidas
    }

    aeronave_atual = None
    cliente_atual = None
    secao_especial = None  # "stand_by", "folga_regular", "coordenacao", "stand_by_voare"

    # Padrões
    RE_AERONAVE = re.compile(
        r"(caravan|cessna\s*206\s*/?\s*210|cessna|caravan\s*208)",
        re.IGNORECASE
    )
    RE_CLIENTE = re.compile(
        r"^\*?(yanomami|leste|voare|norte|sul|oeste|centro|saude)\*?$",
        re.IGNORECASE
    )
    RE_TIPO_OMA = re.compile(
        r"^(pax|carga|vazio|remo[çc][aã]o|remocao|ferry)\s*[-–]?\s*(\d+)?$",
        re.IGNORECASE
    )
    RE_MATRICULA_PILOTO = re.compile(
        r"^([A-Z×xX]{2,3}[-–]?[A-Z×xX0-9]{2,3})\s+(.+)$",
        re.IGNORECASE
    )
    RE_ROTA = re.compile(r"[/›>]")
    RE_OBS = re.compile(r"^obs\s*[:.]?\s*(.+)$", re.IGNORECASE)
    RE_STAND_BY = re.compile(r"^stand\s*by\s*(voare)?$", re.IGNORECASE)
    RE_FOLGA = re.compile(r"^folga\s*(regular)?$", re.IGNORECASE)
    RE_COORD = re.compile(r"^coordena[çc][aã]o$", re.IGNORECASE)

    # Normaliza separadores de seção (===, ---, ***, >>)
    RE_SEPARADOR = re.compile(r"^[=\-*_]{3,}$")
    RE_SECAO_HEADER = re.compile(r"^[_*]*>>?\s*(.+?)\s*<<?[_*]*$")

    voo_buffer = None  # voo sendo construído

    def flush_voo():
        nonlocal voo_buffer
        if voo_buffer and aeronave_atual and cliente_atual:
            if aeronave_atual not in resultado["aeronaves"]:
                resultado["aeronaves"][aeronave_atual] = {}
            if cliente_atual not in resultado["aeronaves"][aeronave_atual]:
                resultado["aeronaves"][aeronave_atual][cliente_atual] = []
            resultado["aeronaves"][aeronave_atual][cliente_atual].append(voo_buffer)
        voo_buffer = None

    def normaliza_aeronave(texto):
        t = texto.upper()
        if "CARAVAN" in t or "208" in t:
            return "CARAVAN"
        if "CESSNA" in t or "206" in t or "210" in t:
            return "CESSNA 206/210"
        return t.strip()

    def normaliza_tipo(texto):
        t = texto.upper().strip()
        mapa = {
            "PAX": "Pax",
            "CARGA": "Carga",
            "VAZIO": "Vazio",
            "REMOCAO": "Remoção",
            "REMOÇÃO": "Remoção",
            "FERRY": "Ferry",
        }
        for k, v in mapa.items():
            if t.startswith(k):
                return v
        return texto.strip().capitalize()

    def parse_tripulacao(texto):
        """Retorna lista de nomes da tripulação."""
        # Remove espaços extras e divide por / ou ,
        partes = re.split(r"\s*/\s*|\s*,\s*", texto.strip())
        return [p.strip() for p in partes if p.strip()]

    def parse_rota(texto):
        """Retorna lista de pontos da rota."""
        partes = re.split(r"\s*[/›>]\s*", texto.strip())
        return [p.strip() for p in partes if p.strip()]

    i = 0
    while i < len(linhas):
        linha = linhas[i]
        linha_limpa = re.sub(r"[_*]", "", linha).strip()

        # Separadores decorativos → ignora
        if RE_SEPARADOR.match(linha_limpa) or not linha_limpa:
            i += 1
            continue

        # Header de seção tipo >> CARAVAN <<
        m_secao = RE_SECAO_HEADER.match(linha)
        if m_secao:
            conteudo = m_secao.group(1)
            flush_voo()
            if RE_AERONAVE.search(conteudo):
                aeronave_atual = normaliza_aeronave(conteudo)
                cliente_atual = None
                secao_especial = None
            i += 1
            continue

        # Detecta aeronave (linha com só o nome da aeronave)
        if RE_AERONAVE.match(linha_limpa):
            flush_voo()
            aeronave_atual = normaliza_aeronave(linha_limpa)
            cliente_atual = None
            secao_especial = None
            i += 1
            continue

        # Detecta cliente (linha com nome do cliente em negrito ou sozinho)
        if RE_CLIENTE.match(linha_limpa):
            flush_voo()
            cliente_atual = linha_limpa.strip("*_ ").capitalize()
            secao_especial = None
            i += 1
            continue

        # Seções especiais
        m_sb = RE_STAND_BY.match(linha_limpa)
        if m_sb:
            flush_voo()
            secao_especial = "stand_by_voare" if m_sb.group(1) else "stand_by"
            i += 1
            continue

        if RE_FOLGA.match(linha_limpa):
            flush_voo()
            secao_especial = "folga_regular"
            i += 1
            continue

        if RE_COORD.match(linha_limpa):
            flush_voo()
            secao_especial = "coordenacao"
            i += 1
            continue

        # Dentro de seções especiais → captura nomes
        if secao_especial in ("stand_by", "folga_regular", "coordenacao", "stand_by_voare"):
            # Ignora sub-títulos como "Voare"
            if not RE_CLIENTE.match(linha_limpa) and not RE_AERONAVE.match(linha_limpa):
                nomes = [n.strip() for n in re.split(r"[,\n]+", linha_limpa) if n.strip()]
                resultado[secao_especial].extend(nomes)
            i += 1
            continue

        # Linha de tipo/OMA: "Pax - 3025" ou "Carga" ou "Remoção - 31"
        m_tipo = RE_TIPO_OMA.match(linha_limpa)
        if m_tipo:
            flush_voo()
            tipo_raw = m_tipo.group(1)
            oma_raw = m_tipo.group(2) or ""
            voo_buffer = {
                "tipo": normaliza_tipo(tipo_raw),
                "oma": oma_raw.strip(),
                "matricula": "××-××",
                "tripulacao": [],
                "rota": [],
                "obs": "",
            }
            i += 1
            continue

        # Linha de matrícula + piloto: "JSA Leandro" ou "××-×× A definir"
        m_matr = RE_MATRICULA_PILOTO.match(linha_limpa)
        if m_matr:
            if voo_buffer is None:
                # Às vezes vem sem tipo antes → cria buffer genérico
                flush_voo()
                voo_buffer = {
                    "tipo": "Pax",
                    "oma": "",
                    "matricula": "××-××",
                    "tripulacao": [],
                    "rota": [],
                    "obs": "",
                }
            matricula = m_matr.group(1).upper().replace("×", "×")
            tripulacao_raw = m_matr.group(2)
            voo_buffer["matricula"] = matricula
            voo_buffer["tripulacao"] = parse_tripulacao(tripulacao_raw)
            i += 1
            continue

        # Linha de rota: contém / ou › ou >
        if RE_ROTA.search(linha_limpa) and voo_buffer is not None:
            voo_buffer["rota"] = parse_rota(linha_limpa)
            i += 1
            continue

        # Linha de observação
        m_obs = RE_OBS.match(linha_limpa)
        if m_obs and voo_buffer is not None:
            voo_buffer["obs"] = m_obs.group(1).strip()
            i += 1
            continue

        # Linha não reconhecida dentro de um contexto de voo → pode ser rota sem separador
        if voo_buffer is not None and not voo_buffer["rota"] and linha_limpa:
            # Tenta como rota sem separador (ex: "Swpd Surucucu Swpd")
            partes = linha_limpa.split()
            if len(partes) >= 2 and all(len(p) >= 3 for p in partes):
                voo_buffer["rota"] = partes
                i += 1
                continue

        # Não reconhecido
        if linha_limpa:
            resultado["erros"].append(f"Linha {i+1}: '{linha}'")
        i += 1

    flush_voo()
    return resultado


# ===== ROTAS =====

def register_routes(app, db_instance):
    """
    Registra as rotas no app Flask.
    Chame assim no app.py:
        from programacao import register_routes
        register_routes(app, db)
    """

    # Importa os models do app principal para criar as tabelas de programação
    from sqlalchemy import Column, Integer, String, Text, Date, DateTime, ForeignKey
    from sqlalchemy.orm import relationship

    class VooDia(db_instance.Model):
        __tablename__ = "voo_dia"
        __table_args__ = {"extend_existing": True}
        id = Column(Integer, primary_key=True)
        data = Column(String(10), nullable=False, index=True)  # "2026-06-13"
        aeronave = Column(String(30), nullable=False)          # "CESSNA 206/210" ou "CARAVAN"
        cliente = Column(String(50), nullable=True)            # "Yanomami", "Leste", etc.
        tipo = Column(String(20), nullable=False)              # "Pax", "Carga", etc.
        oma = Column(String(20), nullable=True)
        matricula = Column(String(15), nullable=True)
        tripulacao = Column(String(200), nullable=True)        # "Piloto / Copiloto"
        rota = Column(String(300), nullable=True)              # "Swpd / Surucucu / Swpd"
        obs = Column(Text, nullable=True)
        ordem = Column(Integer, default=0)
        criado_em = Column(DateTime, default=datetime.utcnow)
        atualizado_em = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    class CienteVoo(db_instance.Model):
        __tablename__ = "ciente_voo"
        __table_args__ = {"extend_existing": True}
        id = Column(Integer, primary_key=True)
        voo_id = Column(Integer, ForeignKey("voo_dia.id"), nullable=False)
        nome_piloto = Column(String(80), nullable=False)
        ciente = Column(db_instance.Boolean, default=False)
        atualizado_em = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    class InfoDia(db_instance.Model):
        __tablename__ = "info_dia"
        __table_args__ = {"extend_existing": True}
        id = Column(Integer, primary_key=True)
        data = Column(String(10), unique=True, nullable=False)
        stand_by = Column(Text, nullable=True)         # JSON list
        folga_regular = Column(Text, nullable=True)
        coordenacao = Column(Text, nullable=True)
        stand_by_voare = Column(Text, nullable=True)

    with app.app_context():
        db_instance.create_all()

    # ── Página principal ──
    @app.route("/programacao")
    @app.route("/programacao/<data_str>")
    def programacao(data_str=None):
        if data_str is None:
            data_str = datetime.now().strftime("%Y-%m-%d")
        return render_template("programacao.html", data_atual=data_str)

    # ── API: Listar voos de uma data ──
    @app.route("/api/programacao/<data_str>", methods=["GET"])
    def api_get_programacao(data_str):
        import json
        voos = VooDia.query.filter_by(data=data_str).order_by(
            VooDia.aeronave, VooDia.cliente, VooDia.ordem
        ).all()

        # Busca ciência
        todos_voo_ids = [v.id for v in voos]
        ciencias = {}
        if todos_voo_ids:
            registros = CienteVoo.query.filter(CienteVoo.voo_id.in_(todos_voo_ids)).all()
            for r in registros:
                if r.voo_id not in ciencias:
                    ciencias[r.voo_id] = {}
                ciencias[r.voo_id][r.nome_piloto] = r.ciente

        info = InfoDia.query.filter_by(data=data_str).first()

        # Agrupa por aeronave > cliente
        aeronaves = {}
        for v in voos:
            ac = v.aeronave
            cl = v.cliente or "Geral"
            if ac not in aeronaves:
                aeronaves[ac] = {}
            if cl not in aeronaves[ac]:
                aeronaves[ac][cl] = []
            aeronaves[ac][cl].append({
                "id": v.id,
                "tipo": v.tipo,
                "oma": v.oma or "",
                "matricula": v.matricula or "××-××",
                "tripulacao": v.tripulacao or "",
                "rota": v.rota or "",
                "obs": v.obs or "",
                "ciencias": ciencias.get(v.id, {}),
            })

        return jsonify({
            "data": data_str,
            "aeronaves": aeronaves,
            "stand_by": json.loads(info.stand_by or "[]") if info else [],
            "folga_regular": json.loads(info.folga_regular or "[]") if info else [],
            "coordenacao": json.loads(info.coordenacao or "[]") if info else [],
            "stand_by_voare": json.loads(info.stand_by_voare or "[]") if info else [],
            "total_voos": len(voos),
        })

    # ── API: Importar programação via texto ──
    @app.route("/api/programacao/importar", methods=["POST"])
    def api_importar_programacao():
        import json
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "erro": "Dados inválidos"}), 400

        texto = data.get("texto", "").strip()
        data_str = data.get("data", datetime.now().strftime("%Y-%m-%d"))

        if not texto:
            return jsonify({"success": False, "erro": "Texto vazio"}), 400

        parsed = parse_programacao(texto, data_str)
        return jsonify({"success": True, "preview": parsed})

    # ── API: Salvar programação (após confirmação do preview) ──
    @app.route("/api/programacao/salvar", methods=["POST"])
    def api_salvar_programacao():
        import json
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "erro": "Dados inválidos"}), 400

        data_str = data.get("data", "")
        if not data_str:
            return jsonify({"success": False, "erro": "Data não informada"}), 400

        # Apaga a programação do dia se já existir
        VooDia.query.filter_by(data=data_str).delete()
        InfoDia.query.filter_by(data=data_str).delete()
        db_instance.session.commit()

        aeronaves = data.get("aeronaves", {})
        ordem = 0
        for aeronave, clientes in aeronaves.items():
            for cliente, voos in clientes.items():
                for voo in voos:
                    tripulacao_str = " / ".join(voo.get("tripulacao", []))
                    rota_str = " / ".join(voo.get("rota", []))
                    novo = VooDia(
                        data=data_str,
                        aeronave=aeronave,
                        cliente=cliente,
                        tipo=voo.get("tipo", "Pax"),
                        oma=voo.get("oma", ""),
                        matricula=voo.get("matricula", "××-××"),
                        tripulacao=tripulacao_str,
                        rota=rota_str,
                        obs=voo.get("obs", ""),
                        ordem=ordem,
                    )
                    db_instance.session.add(novo)
                    ordem += 1

        # Salva info do dia
        info = InfoDia(
            data=data_str,
            stand_by=json.dumps(data.get("stand_by", []), ensure_ascii=False),
            folga_regular=json.dumps(data.get("folga_regular", []), ensure_ascii=False),
            coordenacao=json.dumps(data.get("coordenacao", []), ensure_ascii=False),
            stand_by_voare=json.dumps(data.get("stand_by_voare", []), ensure_ascii=False),
        )
        db_instance.session.add(info)
        db_instance.session.commit()

        return jsonify({"success": True, "total": ordem})

    # ── API: Editar um voo ──
    @app.route("/api/programacao/voo/<int:voo_id>", methods=["PUT"])
    def api_editar_voo(voo_id):
        voo = VooDia.query.get_or_404(voo_id)
        data = request.get_json()
        voo.tipo = data.get("tipo", voo.tipo)
        voo.oma = data.get("oma", voo.oma)
        voo.matricula = data.get("matricula", voo.matricula)
        tripulacao = data.get("tripulacao", None)
        if tripulacao is not None:
            if isinstance(tripulacao, list):
                voo.tripulacao = " / ".join(tripulacao)
            else:
                voo.tripulacao = str(tripulacao)
        rota = data.get("rota", None)
        if rota is not None:
            if isinstance(rota, list):
                voo.rota = " / ".join(rota)
            else:
                voo.rota = str(rota)
        voo.obs = data.get("obs", voo.obs)
        voo.atualizado_em = datetime.utcnow()
        db_instance.session.commit()
        return jsonify({"success": True})

    # ── API: Excluir um voo ──
    @app.route("/api/programacao/voo/<int:voo_id>", methods=["DELETE"])
    def api_excluir_voo(voo_id):
        voo = VooDia.query.get_or_404(voo_id)
        CienteVoo.query.filter_by(voo_id=voo_id).delete()
        db_instance.session.delete(voo)
        db_instance.session.commit()
        return jsonify({"success": True})

    # ── API: Adicionar voo manualmente ──
    @app.route("/api/programacao/voo", methods=["POST"])
    def api_adicionar_voo():
        data = request.get_json()
        data_str = data.get("data", "")
        if not data_str:
            return jsonify({"success": False, "erro": "Data não informada"}), 400

        tripulacao = data.get("tripulacao", [])
        if isinstance(tripulacao, list):
            tripulacao_str = " / ".join(tripulacao)
        else:
            tripulacao_str = str(tripulacao)

        rota = data.get("rota", [])
        if isinstance(rota, list):
            rota_str = " / ".join(rota)
        else:
            rota_str = str(rota)

        ultimo = VooDia.query.filter_by(data=data_str).order_by(VooDia.ordem.desc()).first()
        ordem = (ultimo.ordem + 1) if ultimo else 0

        novo = VooDia(
            data=data_str,
            aeronave=data.get("aeronave", "CESSNA 206/210"),
            cliente=data.get("cliente", "Yanomami"),
            tipo=data.get("tipo", "Pax"),
            oma=data.get("oma", ""),
            matricula=data.get("matricula", "××-××"),
            tripulacao=tripulacao_str,
            rota=rota_str,
            obs=data.get("obs", ""),
            ordem=ordem,
        )
        db_instance.session.add(novo)
        db_instance.session.commit()
        return jsonify({"success": True, "id": novo.id})

    # ── API: Marcar/desmarcar ciente ──
    @app.route("/api/programacao/ciente", methods=["POST"])
    def api_ciente():
        data = request.get_json()
        voo_id = data.get("voo_id")
        nome = data.get("nome", "").strip()
        ciente = data.get("ciente", True)

        if not voo_id or not nome:
            return jsonify({"success": False}), 400

        registro = CienteVoo.query.filter_by(voo_id=voo_id, nome_piloto=nome).first()
        if registro:
            registro.ciente = ciente
            registro.atualizado_em = datetime.utcnow()
        else:
            registro = CienteVoo(voo_id=voo_id, nome_piloto=nome, ciente=ciente)
            db_instance.session.add(registro)

        db_instance.session.commit()
        return jsonify({"success": True, "ciente": ciente})

    # ── API: Clonar dia anterior ──
    @app.route("/api/programacao/clonar", methods=["POST"])
    def api_clonar():
        import json
        data = request.get_json()
        data_destino = data.get("data_destino", "")
        data_origem = data.get("data_origem", "")

        if not data_destino or not data_origem:
            return jsonify({"success": False, "erro": "Datas não informadas"}), 400

        # Verifica se já existe programação no destino
        existente = VooDia.query.filter_by(data=data_destino).first()
        if existente:
            return jsonify({
                "success": False,
                "erro": f"Já existe programação para {data_destino}. Apague primeiro."
            }), 409

        # Clona voos
        voos_origem = VooDia.query.filter_by(data=data_origem).order_by(VooDia.ordem).all()
        for v in voos_origem:
            novo = VooDia(
                data=data_destino,
                aeronave=v.aeronave,
                cliente=v.cliente,
                tipo=v.tipo,
                oma="",  # OMA não clona (muda todo dia)
                matricula=v.matricula,
                tripulacao=v.tripulacao,
                rota=v.rota,
                obs=v.obs,
                ordem=v.ordem,
            )
            db_instance.session.add(novo)

        # Clona info do dia
        info_origem = InfoDia.query.filter_by(data=data_origem).first()
        if info_origem:
            nova_info = InfoDia(
                data=data_destino,
                stand_by=info_origem.stand_by,
                folga_regular=info_origem.folga_regular,
                coordenacao=info_origem.coordenacao,
                stand_by_voare=info_origem.stand_by_voare,
            )
            db_instance.session.add(nova_info)

        db_instance.session.commit()
        return jsonify({"success": True, "clonados": len(voos_origem)})

    # ── API: Listar datas com programação ──
    @app.route("/api/programacao/datas", methods=["GET"])
    def api_listar_datas():
        datas = db_instance.session.query(VooDia.data).distinct().order_by(
            VooDia.data.desc()
        ).limit(30).all()
        return jsonify({"datas": [d[0] for d in datas]})

    # ── API: Apagar programação de um dia ──
    @app.route("/api/programacao/<data_str>", methods=["DELETE"])
    def api_apagar_dia(data_str):
        voos = VooDia.query.filter_by(data=data_str).all()
        for v in voos:
            CienteVoo.query.filter_by(voo_id=v.id).delete()
        VooDia.query.filter_by(data=data_str).delete()
        InfoDia.query.filter_by(data=data_str).delete()
        db_instance.session.commit()
        return jsonify({"success": True})
