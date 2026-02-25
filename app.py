import os
import re
import sys
import math
import io
import stat  # Importado para verificar permissões
import chess
import chess.pgn
import chess.engine
from flask import Flask, render_template, jsonify, request

app = Flask(__name__)

# --- CONFIGURAÇÕES DA ENGINE (ADAPTADO PARA LINUX) ---

# Define o diretório base onde o app.py está
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Caminho baseado na sua imagem: pasta 'stockfish' -> arquivo 'stockfish-ubuntu-...'
# Se o seu servidor não suportar AVX2, você precisará compilar uma versão diferente.
ENGINE_BINARY = "stockfish-ubuntu-x86-64-avx2"
ENGINE_PATH = os.path.join(BASE_DIR, "stockfish", ENGINE_BINARY)

OUT_FILE = os.path.join(BASE_DIR, 'out.txt')
ANALYSIS_DEPTH = 16 

# --- FUNÇÃO PARA GARANTIR PERMISSÃO DE EXECUÇÃO (LINUX) ---
def ensure_executable(path):
    """Garante que o stockfish tenha permissão +x no Linux"""
    try:
        st = os.stat(path)
        os.chmod(path, st.st_mode | stat.S_IEXEC)
    except Exception as e:
        print(f"Aviso: Não foi possível alterar permissões da engine: {e}")

# --- FUNÇÕES DE PARSE DO FRONTEND ---
def parse_eval(eval_str):
    try:
        clean = eval_str.replace('+', '').replace('#', '').strip()
        if 'M' in clean:
            return 20.0 if '-' not in clean else -20.0
        return float(clean)
    except:
        return 0.0

def clean_best_move(raw_text):
    if not raw_text or raw_text == '-': return None
    txt = raw_text.replace('(', '').replace(')', '').replace('Era', '').replace('Best', '').replace('Melhor', '').strip()
    txt = re.sub(r'[^\w\d]', '', txt)
    return txt if len(txt) > 1 else None

def get_game_data():
    moves_data = []
    board = chess.Board()

    # Estado Inicial
    moves_data.append({
        'ply': 0, 'fen': board.fen(), 'move': 'Início', 'author': '-',
        'eval': '0.00', 'eval_val': 0.0, 'analysis': 'Posição Inicial', 'arrow': None
    })

    if not os.path.exists(OUT_FILE):
        return moves_data

    try:
        with open(OUT_FILE, 'r', encoding='utf-8') as f: lines = f.readlines()
    except UnicodeDecodeError:
        with open(OUT_FILE, 'r', encoding='latin-1') as f: lines = f.readlines()

    ply_count = 0
    for line in lines:
        parts = [p.strip() for p in line.split('|')]
        if len(parts) < 6: continue
        if '#' in parts[0] or 'Quem' in parts[1] or '----' in line: continue

        author = parts[1]
        move_san = parts[2]
        eval_score = parts[3]
        raw_best = parts[4]
        analysis_text = parts[5]

        arrow_data = None
        suggested_san = clean_best_move(raw_best)
        if suggested_san:
            try:
                move_obj = board.parse_san(suggested_san)
                uci = move_obj.uci()
                arrow_data = {'from': uci[:2], 'to': uci[2:4]}
            except ValueError:
                arrow_data = None
        
        if arrow_data:
            moves_data[-1]['arrow'] = arrow_data

        try:
            move = board.parse_san(move_san)
            board.push(move)
            ply_count += 1
            
            raw_val = parse_eval(eval_score)
            final_val = -raw_val if ('Pretas' in author or 'Black' in author) else raw_val

            moves_data.append({
                'ply': ply_count, 'fen': board.fen(), 'move': move_san,
                'author': author, 'eval': eval_score, 'eval_val': final_val,
                'analysis': analysis_text, 'arrow': None
            })
        except ValueError:
            continue

    return moves_data

# --- LÓGICA DE ANÁLISE ---
def to_centipawns(score):
    return score.score(mate_score=10000)

def calcular_chance_vitoria(cp):
    if cp is None: return 0.5
    cp = max(-1000, min(1000, cp))
    return 1 / (1 + math.exp(-0.00368208 * cp))

def classificar_lance(diff_win_percent, diff_cp):
    perda_pct = diff_win_percent * 100 
    if perda_pct <= 1.5: return "Excelente"
    elif perda_pct <= 5: return "Bom"
    elif perda_pct <= 12: return "Imprecisão"
    elif perda_pct <= 25: return "Erro"
    else: return "Erro Grave"

def formatar_score(score):
    if score.is_mate():
        return f"M{score.mate()}"
    
    val = score.score()
    if val is not None:
        if val > 2000: return "+20.00"
        if val < -2000: return "-20.00"
        return f"{val / 100:+.2f}"
    
    return "0.00"

def run_analysis(pgn_text):
    """Executa o Stockfish e gera o arquivo out.txt"""
    print("Iniciando análise...")
    
    # Validação do binário
    if not os.path.exists(ENGINE_PATH):
        return {"error": f"Engine não encontrada em: {ENGINE_PATH}"}
    
    # Garante permissão de execução no Linux
    ensure_executable(ENGINE_PATH)

    try:
        pgn_io = io.StringIO(pgn_text)
        game = chess.pgn.read_game(pgn_io)
        if game is None:
            return {"error": "PGN Inválido ou vazio"}

        board = game.board()
        
        # Inicia a Engine
        engine = chess.engine.SimpleEngine.popen_uci(ENGINE_PATH)
        engine.configure({"Threads": 2, "Hash": 64})

        results_buffer = []
        results_buffer.append(f"{'#':<4} | {'Quem':<7} | {'Lance':<7} | {'Eval':<7} | {'Melhor':<8} | {'Classificação'}\n")
        results_buffer.append("-" * 90 + "\n")

        for move in game.mainline_moves():
            full_num = board.fullmove_number
            turn_color = "Brancas" if board.turn == chess.WHITE else "Pretas"

            # 1. Analisar ANTES
            info_antes = engine.analyse(board, chess.engine.Limit(depth=ANALYSIS_DEPTH))
            score_antes = info_antes["score"].pov(board.turn)
            cp_antes = to_centipawns(score_antes)
            win_chance_antes = calcular_chance_vitoria(cp_antes)
            
            melhor_lance_uci = info_antes["pv"][0] if "pv" in info_antes else None
            melhor_lance_san = board.san(melhor_lance_uci) if melhor_lance_uci else "-"

            lance_jogado_san = board.san(move)
            
            # 2. Executa lance
            board.push(move)

            # 3. Analisar DEPOIS
            info_depois = engine.analyse(board, chess.engine.Limit(depth=ANALYSIS_DEPTH))
            score_depois = info_depois["score"].pov(not board.turn) 
            cp_depois = to_centipawns(score_depois)
            win_chance_depois = calcular_chance_vitoria(cp_depois)

            # 4. Cálculos
            diff_cp = max(0, cp_antes - cp_depois)
            diff_win = max(0, win_chance_antes - win_chance_depois)
            
            # 5. Classificação
            sugestao = "-"
            e_o_melhor = (melhor_lance_uci and move == melhor_lance_uci)
            
            if e_o_melhor:
                classificacao = "Melhor"
                sugestao = "-"
            else:
                classificacao = classificar_lance(diff_win, diff_cp)
                sugestao = melhor_lance_san

            line = f"{full_num:<4} | {turn_color:<7} | {lance_jogado_san:<7} | {formatar_score(score_depois):<7} | {sugestao:<8} | {classificacao}\n"
            results_buffer.append(line)

        engine.quit()

        with open(OUT_FILE, "w", encoding="utf-8") as f:
            f.writelines(results_buffer)

        return {"success": True}

    except Exception as e:
        if 'engine' in locals(): engine.quit()
        return {"error": str(e)}

# --- ROTAS FLASK ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/data')
def data():
    return jsonify(get_game_data())

@app.route('/submit', methods=['POST'])
def submit_game():
    data = request.json
    pgn_content = data.get('pgn')
    
    if not pgn_content:
        return jsonify({"error": "Nenhum PGN fornecido"}), 400

    result = run_analysis(pgn_content)
    
    if "error" in result:
        return jsonify(result), 500
        
    return jsonify(result)

if __name__ == '__main__':
    # host='0.0.0.0' permite acesso externo se estiver rodando num servidor
    app.run(debug=True, host='0.0.0.0', port=5000)
