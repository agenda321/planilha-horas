import os
from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from escala import ESCALA_MENSAL
from flask_cors import CORS

app = Flask(__name__)

# Configuração do banco de dados
database_url = os.environ.get("DATABASE_URL", "postgresql://user:password@localhost/mydatabase")
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

CORS(app)

EDIT_PASSWORD = os.environ.get("EDIT_PASSWORD", "Emerson")
EDIT_PASSWORD_2 = os.environ.get("EDIT_PASSWORD_2", "Bispo")

CODIGOS_DISPONIVEIS = ["VO", "CQ", "RE", "SO", "EA", "TR", "TN"]

CORES = {
    "DM": "laranja",
    "CM": "laranja_claro",
    "VO": "azul",
    "EA": "amarelo",
    "FR": "verde",
    "FS": "vermelho",
    "FE": "verde_claro",
    "RE": "rosa",
    "SO": "branco",
    "TR": "amarelo_escuro",
    "TN": "azul_claro",
    "CQ": "azul_medio"
}

class Pilot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    full_name = db.Column(db.String(120), nullable=True)
    group = db.Column(db.String(50), nullable=False)

class FlightLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    pilot_id = db.Column(db.Integer, db.ForeignKey("pilot.id"), nullable=False)
    day = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    year = db.Column(db.Integer, nullable=False)
    hours = db.Column(db.Float, nullable=False, default=0.0)
    pilot = db.relationship("Pilot", backref=db.backref("flight_logs", lazy=True))

class StatusOverride(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    pilot_id = db.Column(db.Integer, db.ForeignKey("pilot.id"), nullable=False)
    day = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    year = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(10), nullable=False)
    pilot = db.relationship("Pilot", backref=db.backref("status_overrides", lazy=True))

def normalizar_status(status):
    if status is None or status == "" or status == " ":
        return "VO"
    return status

def obtener_escala_dinamica(pilot_obj, month, year):
    escala = list(ESCALA_MENSAL.get(pilot_obj.name, []))
    if not escala:
        return escala
    overrides = StatusOverride.query.filter_by(pilot_id=pilot_obj.id, month=month, year=year).all()
    for ov in overrides:
        if ov.day < len(escala):
            escala[ov.day] = ov.status
    logs = FlightLog.query.filter_by(pilot_id=pilot_obj.id, month=month, year=year).all()
    dias_com_horas = {log.day for log in logs if log.hours > 0}
    limite = min(10, len(escala))
    for i in range(limite):
        dia_num = i + 1
        if dia_num in dias_com_horas and escala[i] == "FR":
            sub_idx = i + 1
            while sub_idx < len(escala):
                sub_dia_num = sub_idx + 1
                if escala[sub_idx] == "SO" and sub_dia_num not in dias_com_horas:
                    escala[i] = "SO"
                    escala[sub_idx] = "FR"
                    break
                sub_idx += 1
    return escala

# ============================
# ROTAS
# ============================

# Landing page (estática)
@app.route("/")
def landing():
    return app.send_static_file('index.html')

# Planilha
@app.route("/planilha")
def planilha():
    return render_template("planilha.html")

# API de login
@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json()
    if data.get("password") in [EDIT_PASSWORD, EDIT_PASSWORD_2]:
        return jsonify({"success": True})
    return jsonify({"success": False}), 401

# API de dados
@app.route("/api/data", methods=["GET"])
def get_data():
    month, year = datetime.now().month, datetime.now().year
    pilots = Pilot.query.all()
    logs = FlightLog.query.filter_by(month=month, year=year).all()
    result = {
        "pilots": [{"name": p.name, "group": p.group, "full_name": p.full_name or p.name} for p in pilots],
        "logs": {}
    }
    for log in logs:
        if log.pilot.name not in result["logs"]:
            result["logs"][log.pilot.name] = {}
        result["logs"][log.pilot.name][log.day] = log.hours
    return jsonify(result)

@app.route("/api/data", methods=["POST"])
def save_data():
    data = request.get_json()
    if data.get("password") not in [EDIT_PASSWORD, EDIT_PASSWORD_2]:
        return jsonify({"success": False}), 401
    month, year = datetime.now().month, datetime.now().year
    for pilot_name, days in data.get("logs", {}).items():
        pilot = Pilot.query.filter_by(name=pilot_name).first()
        if not pilot:
            continue
        for day_str, hours in days.items():
            day = int(day_str)
            if hours is None or str(hours).strip() == "":
                valor_horas = 0.0
            else:
                try:
                    valor_horas = float(hours)
                except ValueError:
                    valor_horas = 0.0
            log = FlightLog.query.filter_by(pilot_id=pilot.id, day=day, month=month, year=year).first()
            if log:
                log.hours = valor_horas
            else:
                db.session.add(FlightLog(pilot_id=pilot.id, day=day, month=month, year=year, hours=valor_horas))
    db.session.commit()
    return jsonify({"success": True})

# API de disponíveis
@app.route("/api/available_commanders/<int:day_index>", methods=["GET"])
def get_available_commanders(day_index):
    pilotos_com_horas = {"CESSNA 206/210": [], "CARAVAN": [], "COPILOTO": []}
    pilots = Pilot.query.all()
    month, year = datetime.now().month, datetime.now().year
    dia_solicitado = day_index + 1
    for pilot in pilots:
        escala = obtener_escala_dinamica(pilot, month, year)
        if not escala:
            escala = ESCALA_MENSAL.get(pilot.name, [])
        if day_index < len(escala):
            raw_status = escala[day_index]
            status = normalizar_status(raw_status)
            cor = CORES.get(status, "cinza")
        else:
            status = "VO"
            cor = "azul"
        if status in CODIGOS_DISPONIVEIS:
            logs = FlightLog.query.filter_by(pilot_id=pilot.id, month=month, year=year).all()
            horas_acumuladas = sum(log.hours for log in logs if log.day <= dia_solicitado)
            pilotos_com_horas[pilot.group].append({
                "name": pilot.full_name or pilot.name,
                "status": status,
                "color": cor,
                "horas_totais": horas_acumuladas
            })
    available = {}
    for grupo, lista_pilotos in pilotos_com_horas.items():
        available[grupo] = sorted(lista_pilotos, key=lambda x: x["horas_totais"], reverse=True)
    return jsonify(available)

# API de atualização de status (toque longo)
@app.route("/api/update_status", methods=["POST"])
def update_status():
    data = request.get_json()
    pilot_name = data.get("pilot")
    day = data.get("day")
    new_status = data.get("status")
    month, year = datetime.now().month, datetime.now().year
    if not pilot_name or day is None or not new_status:
        return jsonify({"success": False, "erro": "Dados incompletos"}), 400
    pilot = Pilot.query.filter_by(name=pilot_name).first()
    if not pilot:
        return jsonify({"success": False, "erro": "Piloto não encontrado"}), 404
    override = StatusOverride.query.filter_by(pilot_id=pilot.id, day=day, month=month, year=year).first()
    if override:
        override.status = new_status
    else:
        override = StatusOverride(pilot_id=pilot.id, day=day, month=month, year=year, status=new_status)
        db.session.add(override)
    db.session.commit()
    return jsonify({"success": True})

# Debug: reset banco
@app.route("/api/debug/reset-banco")
def reset_banco():
    db.drop_all()
    db.create_all()
    povoar_dados_iniciais()
    return "Banco reiniciado e dados da planilha carregados com sucesso!"

def povoar_dados_iniciais():
    grupos = {
        "Andre": "CESSNA 206/210", "Andrade": "CESSNA 206/210", "Adelio": "CESSNA 206/210",
        "Amarildo": "CESSNA 206/210", "Cleverson": "CESSNA 206/210", "Hazafe": "CESSNA 206/210",
        "Dayvid": "CESSNA 206/210", "Edson": "CESSNA 206/210", "Frank": "CESSNA 206/210",
        "Gabriel": "CESSNA 206/210", "Igorh": "CESSNA 206/210", "Leandro": "CESSNA 206/210",
        "Luiz": "CESSNA 206/210", "Milton": "CESSNA 206/210", "Paulo": "CESSNA 206/210",
        "Ronie": "CESSNA 206/210", "Sergio": "CESSNA 206/210", "Tarso": "CESSNA 206/210",
        "Otto": "CESSNA 206/210", "Dany": "CESSNA 206/210", "Lucas": "CESSNA 206/210",
        "Roberto": "CESSNA 206/210", "Renan": "CESSNA 206/210", "Wellber": "CESSNA 206/210",
        "Bento": "CESSNA 206/210", "Costa": "CESSNA 206/210", "Vitor": "CESSNA 206/210",
        "Mathias": "CESSNA 206/210",
        "Cleiton": "CARAVAN", "Joao": "CARAVAN", "Pascoal": "CARAVAN",
        "Lindomar": "CARAVAN", "Perisson": "CARAVAN", "Rui": "CARAVAN", "Yago": "CARAVAN",
        "Cauê": "COPILOTO", "Felipe": "COPILOTO", "Ruben": "COPILOTO",
        "Ernesto": "COPILOTO", "Daniela": "COPILOTO", "Thales": "COPILOTO",
        "Serafim": "COPILOTO", "Ronaldo": "COPILOTO", "Rodrigo": "COPILOTO", "Tiago": "COPILOTO"
    }
    nomes_completos = {
        "Adelio": "Adelio Costa Felinto", "Otto": "Albert Otto Azevedo",
        "Andre": "Andre Luis Fernandes", "Cleiton": "Cleiton Taumaturgo",
        "Cleverson": "Cleverson dos Santos", "Edson": "Edson Fonteles Portela",
        "Frank": "Franker Wendell Dias", "Gabriel": "Gabriel de Oliveira",
        "Costa": "Costa", "Hazafe": "Hazafe Pacheco de Alencar",
        "Amarildo": "Joao Amarildo Reis", "Igorh": "Igorh Coutinho Martins",
        "Joao": "Joao Marcus Oliveira",
        "Dayvid": "Jose Deyvid Monteiro",
        "Leandro": "Leandro Magalhães", "Lindomar": "Lindomar Bras Mota",
        "Lucas": "Lucas Alves Pereira", "Luiz": "Luiz Andrade",
        "Mathias": "Mathias Pires de Campos",
        "Milton": "Milton Braga de Souza",
        "Pascoal": "Pascoal Brito de Araujo", "Paulo": "Paulo Andre Silva",
        "Perisson": "Perisson Parmigiani", "Renan": "Renan da Silva Nascimento",
        "Roberto": "Roberto Adolfo Boesing", "Ronie": "Ronie Welter",
        "Rui": "Rui de Almeida Vasconcelos", "Sergio": "Sergio Carneiro Rodrigues",
        "Tarso": "Tarso de Souza Cruz", "Vitor": "Vitor Augusto Fernandes",
        "Bento": "Vitor da Costa Bento", "Wellber": "Wellber Nogueira Barros",
        "Andrade": "Luiz Andrade de Souza", "Yago": "Yago Bezerra Correia",
        "Cauê": "Caue Montanari", "Daniela": "Daniela Goncalves Fabricio",
        "Ernesto": "Ernesto da Silva Kaster", "Ruben": "Francisco Rubenicio Souza",
        "Rodrigo": "Rodrigo Silva Melo", "Ronaldo": "Ronaldo Rodrigues Parreao",
        "Thales": "Thales Araujo Penna", "Serafim": "Tiago Carvalho Serafim",
        "Tiago": "Tiago Pinto Quirino"
    }
    for nome, group in grupos.items():
        piloto = Pilot(name=nome, full_name=nomes_completos.get(nome, nome), group=group)
        db.session.add(piloto)
    db.session.commit()
    m_atual, y_atual = datetime.now().month, datetime.now().year
    dados_foto = {
        "Andrade": {1: 3.4, 2: 6.4, 3: 2.9, 5: 5.9, 6: 7.9, 7: 8.0, 9: 6.8},
        "Amarildo": {1: 5.6, 2: 4.7, 3: 4.8, 4: 6.6, 5: 0.0, 7: 4.9, 8: 4.5},
        "Cleverson": {1: 6.2, 2: 5.9, 4: 7.5, 5: 3.6, 6: 4.8, 7: 8.5},
        "Hazafe": {3: 3.6, 4: 6.7, 8: 8.1},
        "Dayvid": {3: 5.5, 4: 7.5, 8: 7.1},
        "Edson": {1: 6.5, 2: 3.2, 3: 5.3, 4: 6.3, 5: 0.0, 6: 4.3, 8: 7.4, 9: 3.4},
        "Frank": {1: 7.0, 2: 7.2, 4: 6.7, 5: 8.0, 7: 8.0},
        "Gabriel": {1: 5.8, 3: 7.5, 5: 5.4, 6: 2.5, 7: 8.8, 8: 7.2},
        "Igorh": {1: 7.0, 3: 7.5, 5: 7.5, 6: 2.4, 7: 8.0},
        "Leandro": {1: 6.4, 2: 7.0, 3: 6.5, 6: 3.8, 7: 7.3, 8: 8.8},
        "Paulo": {7: 8.2},
        "Ronie": {1: 8.6, 3: 9.2, 4: 8.2, 8: 9.1, 9: 7.0},
        "Sergio": {2: 8.0, 3: 6.0, 4: 8.7, 5: 6.4, 7: 8.2},
        "Tarso": {1: 0.0},
        "Otto": {2: 3.8, 3: 6.4, 4: 1.0, 8: 7.3},
        "Dany": {3: 7.5, 8: 4.0},
        "Lucas": {8: 7.1},
        "Roberto": {1: 3.7, 2: 3.0},
        "Renan": {2: 5.5, 4: 5.5, 5: 6.4, 7: 8.0, 8: 6.0},
        "Wellber": {1: 4.0, 3: 6.3, 4: 7.8, 5: 6.1, 7: 7.8},
        "Bento": {8: 6.2, 9: 6.8},
        "Costa": {1: 3.7, 2: 3.0, 5: 6.6, 6: 2.2, 8: 5.0},
        "Vitor": {2: 7.2, 5: 6.6, 6: 6.2, 7: 8.0},
        "Mathias": {3: 5.2, 4: 6.5, 8: 6.2},
        "Cleiton": {2: 4.6, 3: 6.2},
        "Joao": {2: 3.0, 5: 6.3, 7: 6.6},
        "Pascoal": {6: 2.8},
        "Lindomar": {5: 7.1, 6: 1.0, 7: 7.3},
        "Perisson": {3: 7.7, 8: 2.8, 9: 7.0},
        "Rui": {5: 7.5, 6: 2.9, 7: 7.9},
        "Yago": {3: 7.3, 4: 5.7, 6: 6.1},
        "Cauê": {3: 7.3, 5: 7.1, 7: 8.2},
        "Ruben": {2: 3.0, 4: 5.7, 9: 7.0},
        "Daniela": {6: 2.9, 7: 7.9},
        "Thales": {5: 7.2, 6: 2.8},
        "Serafim": {6: 6.1, 7: 6.6, 8: 2.8},
        "Ronaldo": {7: 7.3},
        "Rodrigo": {3: 6.2, 5: 6.3},
        "Tiago": {3: 7.7}
    }
    for p_name, dias_dados in dados_foto.items():
        p_obj = Pilot.query.filter_by(name=p_name).first()
        if p_obj:
            for d_num, h_val in dias_dados.items():
                db.session.add(FlightLog(pilot_id=p_obj.id, day=d_num, month=m_atual, year=y_atual, hours=float(h_val)))
    db.session.commit()

# Integração com módulo de programação
from programacao import register_routes
register_routes(app, db)

# Inicialização do banco
with app.app_context():
    db.create_all()
    if Pilot.query.count() == 0:
        povoar_dados_iniciais()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=os.environ.get("PORT", 5000))
