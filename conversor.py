import chess
import chess.pgn
import chess.engine
import sys
import math

# --- CONFIGURAÇÃO ---
CAMINHO_STOCKFISH = r"./engine/stockfish/prog.exe" # Confirma o caminho!
ARQUIVO_ENTRADA = "ex.txt"
ARQUIVO_SAIDA = "out.txt"

ENGINE_CONFIG = {"Threads": 4, "Hash": 128}
PROFUNDIDADE = 16 

def to_centipawns(score):
    """Converte score para um valor numérico inteiro (tratando Mate)."""
    # Se for Mate, usamos um valor alto (ex: 10000) mas dentro de um limite tratável
    return score.score(mate_score=10000)

def calcular_chance_vitoria(cp):
    """
    Converte Centipawns para % de vitória (0.0 a 1.0).
    Fórmula ajustada para retornar probabilidade pura (0 a 100%).
    """
    if cp is None: return 0.5
    
    # O clamp em 1000 evita distorções matemáticas extremas
    cp = max(-1000, min(1000, cp))
    
    # Fórmula Lichess simplificada para intervalo 0..1
    # Removemos o '2 * ... - 1' e deixamos a sigmoide pura
    return 1 / (1 + math.exp(-0.00368208 * cp))

def classificar_lance(diff_win_percent, diff_cp):
    """
    Classifica baseado na queda da PROBABILIDADE de vitória (0.0 a 1.0).
    """
    # diff_win_percent agora é algo como 0.15 (15%) ou 0.02 (2%)
    perda_pct = diff_win_percent * 100 

    # --- Lógica de Classificação Padrão ---
    # Valores aproximados usados por sites de análise:
    # < 5%: Perda irrelevante (Melhor lance ou diferença minúscula)
    # 5% - 10%: Imprecisão (Inaccuracy)
    # 10% - 20%: Erro (Mistake)
    # > 20%: Erro Grave (Blunder)
    
    if perda_pct <= 5:
        return "🌟 Excelente / Melhor"
    elif perda_pct <= 10:
        return "✅ Imprecisão"
    elif perda_pct <= 20:
        return "⚠️ Erro (Mistake)"
    else:
        # Blunder requer uma mudança drástica no destino do jogo
        # Ex: Ganho -> Empate, ou Empate -> Perdido
        return "❌ Erro Grave (Blunder)"

def formatar_score(score):
    if score.is_mate():
        return f"M{score.mate()}"
    return f"{score.score() / 100:+.2f}"

def analisar_jogo():
    try:
        engine = chess.engine.SimpleEngine.popen_uci(CAMINHO_STOCKFISH)
        engine.configure(ENGINE_CONFIG)
    except FileNotFoundError:
        print(f"ERRO: Stockfish não encontrado em: {CAMINHO_STOCKFISH}")
        return

    print(f"--- A INICIAR ANÁLISE (MODO INTELIGENTE) ---")
    print(f"A ler '{ARQUIVO_ENTRADA}'...")

    try:
        with open(ARQUIVO_ENTRADA, "r", encoding="utf-8") as pgn_file:
            game = chess.pgn.read_game(pgn_file)
            if game is None:
                print("ERRO: Jogo inválido.")
                return

        board = game.board()
        
        with open(ARQUIVO_SAIDA, "w", encoding="utf-8") as f_out:
            topo = f"{'#':<4} | {'Quem':<7} | {'Lance':<7} | {'Eval':<7} | {'Melhor':<8} | {'Classificação'}\n"
            f_out.write(topo)
            f_out.write("-" * 90 + "\n")
            
            print("A processar lances...")

            for move in game.mainline_moves():
                full_num = board.fullmove_number
                turn_color = "Brancas" if board.turn == chess.WHITE else "Pretas"
                
                # 1. Analisar ANTES (Qual a nossa chance de vitória atual?)
                info_antes = engine.analyse(board, chess.engine.Limit(depth=PROFUNDIDADE))
                score_antes = info_antes["score"].pov(board.turn)
                cp_antes = to_centipawns(score_antes)
                win_chance_antes = calcular_chance_vitoria(cp_antes)

                melhor_lance_uci = info_antes["pv"][0]
                melhor_lance_san = board.san(melhor_lance_uci)
                
                lance_jogado_san = board.san(move)
                
                # 2. Executa o lance
                board.push(move)
                
                # 3. Analisar DEPOIS (Qual a chance agora?)
                # Invertemos a perspectiva para ver como ficou para quem jogou
                info_depois = engine.analyse(board, chess.engine.Limit(depth=PROFUNDIDADE))
                score_depois = info_depois["score"].pov(not board.turn) 
                cp_depois = to_centipawns(score_depois)
                win_chance_depois = calcular_chance_vitoria(cp_depois)

                # 4. Calcular perdas
                # Perda em material (CP)
                diff_cp = max(0, cp_antes - cp_depois)
                
                # Perda em probabilidade de vitória (A MÁGICA ACONTECE AQUI)
                # Se eu tinha 99% de chance e fui para 98%, a diferença é minúscula, mesmo que o CP tenha caído muito.
                diff_win = max(0, win_chance_antes - win_chance_depois)
                
                classificacao = classificar_lance(diff_win, diff_cp)
                
                if move == melhor_lance_uci:
                    classificacao = "🌟 Melhor Lance"
                    sugestao = "-"
                else:
                    sugestao = melhor_lance_san

                linha = f"{full_num:<4} | {turn_color:<7} | {lance_jogado_san:<7} | {formatar_score(score_depois):<7} | {sugestao:<8} | {classificacao}\n"
                f_out.write(linha)
                
                sys.stdout.write(f"\rAnalizado lance {full_num} ({turn_color})...")
                sys.stdout.flush()

            f_out.write("-" * 90 + "\n")
            f_out.write("Análise Concluída.")

    except Exception as e:
        print(f"\nErro: {e}")
    finally:
        engine.quit()
        print(f"\n\nConcluído!")

if __name__ == "__main__":
    analisar_jogo()