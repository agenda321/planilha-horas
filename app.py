import os
from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from escala import ESCALA_MENSAL

app = Flask(__name__)

# Configuração do banco de dados - CORRIGIDO postgres:// → postgresql://
database_url = os.environ.get("DATABASE_URL", "postgresql://user:password@localhost/mydatabase")
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# Senhas de edição - CORRIGIDO para aceitar duas senhas
EDIT_PASSWORD = os.environ.get("EDIT_PASSWORD", "Emerson")
EDIT_PASSWORD_2 = os.environ.get("EDIT_PASSWORD_2", "Bispo")

CODIGOS_DISPONIVEIS = ["VO", "CQ", "RE", "SO"]
CORES = {
    "DM": "laranja", "CM": "laranja_claro", "VO": "azul", "EA": "amarelo",
    "FR": "verde", "FS": "vermelho", "FE": "verde_claro", "RE": "rosa",
    "SO": "branco", "TR": "amarelo_escuro", "TN": "azul_claro", "CQ": "azul_medio"
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

def normalizar_status(status):
    if status is None or status == "" or status == " ":
        return "VO"
    return status

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json()
    if data.get("password") in [EDIT_PASSWORD, EDIT_PASSWORD_2]:
        return jsonify({"success": True})
    return jsonify({"success": False}), 401

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
    # CORRIGIDO: aceita as duas senhas
    if data.get("password") not in [EDIT_PASSWORD, EDIT_PASSWORD_2]:
        return jsonify({"success": False}), 401

    month, year = datetime.now().month, datetime.now().year

    for pilot_name, days in data.get("logs", {}).items():
        pilot = Pilot.query.filter_by(name=pilot_name).first()
        if not pilot:
            continue
        for day_str, hours in days.items():
            day = int(day_str)
            log = FlightLog.query.filter_by(
                pilot_id=pilot.id, day=day, month=month, year=year
            ).first()
            if log:
                log.hours = float(hours)
            else:
                db.session.add(FlightLog(
                    pilot_id=pilot.id, day=day, month=month, year=year, hours=float(hours)
                ))

    db.session.commit()
    return jsonify({"success": True})

@app.route("/api/available_commanders/<int:day_index>", methods=["GET"])
def get_available_commanders(day_index):
    available = {"CESSNA 206/210": [], "CARAVAN": [], "COPILOTO": []}
    pilots = Pilot.query.all()

    for pilot in pilots:
        escala = ESCALA_MENSAL.get(pilot.name, [])
        if day_index < len(escala):
            raw_status = escala[day_index]
            status = normalizar_status(raw_status)
            cor = CORES.get(status, "cinza")
        else:
            status = "VO"
            cor = "azul"

        if status in CODIGOS_DISPONIVEIS:
            available[pilot.group].append({
                "name": pilot.full_name or pilot.name,
                "status": status,
                "color": cor
            })

    return jsonify(available)

with app.app_context():
    db.create_all()

    if Pilot.query.count() == 0:
        grupos = {
            "Andre": "CESSNA 206/210", "Andrade": "CESSNA 206/210", "Adelio": "CESSNA 206/210",
            "Amarildo": "CESSNA 206/210", "Cleverson": "CESSNA 206/210", "Hazafe": "CESSNA 206/210",
            "Deyvid": "CESSNA 206/210", "Edson": "CESSNA 206/210", "Frank": "CESSNA 206/210",
            "Gabriel": "CESSNA 206/210", "Igorh": "CESSNA 206/210", "Leandro": "CESSNA 206/210",
            "Luiz": "CESSNA 206/210", "Milton": "CESSNA 206/210", "Paulo": "CESSNA 206/210",
            "Ronie": "CESSNA 206/210", "Sergio": "CESSNA 206/210", "Tarso": "CESSNA 206/210",
            "Otto": "CESSNA 206/210", "Dany": "CESSNA 206/210", "Lucas": "CESSNA 206/210",
            "Roberto": "CESSNA 206/210", "Renan": "CESSNA 206/210", "Wellber": "CESSNA 206/210",
            "Bento": "CESSNA 206/210", "Costa": "CESSNA 206/210", "Vitor": "CESSNA 206/210",
            "Matias": "CESSNA 206/210",
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
            "Joao": "Joao Marcus Oliveira", "Deyvid": "Jose Deyvid Monteiro",
            "Leandro": "Leandro Magalhães", "Lindomar": "Lindomar Bras Mota",
            "Lucas": "Lucas Alves Pereira", "Luiz": "Luiz Andrade",
            "Matias": "Matias Pires de Campos", "Milton": "Milton Braga de Souza",
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

        for nome, grupo in grupos.items():
            piloto = Pilot(name=nome, full_name=nomes_completos.get(nome, nome), group=grupo)
            db.session.add(piloto)

        db.session.commit()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=os.environ.get("PORT", 5000))
