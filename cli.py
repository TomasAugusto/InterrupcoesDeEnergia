"""Linha de comando do projeto.

    python cli.py amostra            um ano só, do zero ao painel em minutos
    python cli.py mensal             o ciclo mensal inteiro, num comando
    python cli.py atualizar          baixa o que mudou na ANEEL
    python cli.py curar              bronze -> prata
    python cli.py clima              baixa o ERA5 horário de MG
    python cli.py curar-clima        ERA5 -> grade e clima por conjunto
    python cli.py verificar          audita a base curada
    python cli.py publicar           monta a camada ouro para publicação
    python cli.py painel             sobe o dashboard
"""

import argparse
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser

from zeki import config


def _log(verboso=False):
    logging.basicConfig(
        level=logging.DEBUG if verboso else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def cmd_atualizar(args):
    from zeki.fontes import aneel

    config.preparar_diretorios()
    anos = [config.ANO_AMOSTRA] if args.amostra else args.anos
    atualizados = aneel.sincronizar(anos)
    print(f"anos atualizados: {atualizados or 'nenhum'}")


def cmd_curar(args):
    from zeki.curadoria import dimensoes, fato, geometria

    config.preparar_diretorios()
    if not args.so_fato:
        dimensoes.construir()
        # A geometria vem depois das dimensões porque recorta os polígonos do
        # IBGE pela ponte conjunto-município. Sem ela o mapa do painel não
        # existe e `curar-clima` não tem como pesar as células do ERA5.
        geometria.construir()

    anos = [config.ANO_AMOSTRA] if args.amostra else args.anos
    resultado = fato.curar(anos)
    total = sum(resultado.values())
    print(f"{total:,} linhas em {len(resultado)} anos")


def cmd_clima(args):
    from zeki.fontes import era5

    config.preparar_diretorios()
    if args.checar:
        ok, recado = era5.verificar()
        print(recado)
        raise SystemExit(0 if ok else 1)
    era5.construir(ate_mes=args.ate)


def cmd_curar_clima(args):
    from zeki import dados
    from zeki.curadoria import clima

    config.preparar_diretorios()
    clima.pesos()
    clima.grade()
    clima.por_conjunto(dados.conectar())


def cmd_mensal(args):
    """O ciclo que a rotina mensal precisa, num comando só."""
    from zeki import atualizacao

    config.preparar_diretorios()
    if args.conferir:
        pendentes = atualizacao.pendencias()
        if not pendentes["online"]:
            print(f"não consegui falar com o portal da ANEEL: {pendentes['motivo']}")
            raise SystemExit(2)
        print(f"anos desatualizados: {pendentes['anos'] or 'nenhum'}")
        raise SystemExit(1 if pendentes["anos"] or pendentes["ponte"] else 0)

    resultado = atualizacao.executar(anos=args.anos, com_ponte=args.com_ponte,
                                     com_clima=args.com_clima)
    print(f"anos atualizados: {resultado['anos'] or 'nenhum'}")
    if args.com_clima:
        print(f"meses de clima baixados: {len(resultado['clima'])}")


def cmd_verificar(args):
    from zeki import qualidade

    graves = qualidade.auditar()
    raise SystemExit(1 if graves else 0)


def cmd_publicar(args):
    from zeki.curadoria import marts

    resultado = marts.construir()
    total = sum(mb for _, mb in resultado.values())
    print(f"\ncamada ouro: {len(resultado)} arquivos, {total:.1f} MB")
    print("É essa pasta que a versão publicada consome. Para conferir como ela")
    print("fica sem a prata:  python cli.py painel --publicado")


def cmd_amostra(args):
    """Menor caminho até um painel de pé: um ano só, sem clima."""
    from zeki.curadoria import dimensoes, fato, geometria
    from zeki.fontes import aneel

    config.preparar_diretorios()
    aneel.sincronizar([config.ANO_AMOSTRA])
    dimensoes.construir()
    geometria.construir()
    resultado = fato.curar([config.ANO_AMOSTRA])

    print(f"\n{sum(resultado.values()):,} linhas de {config.ANO_AMOSTRA} prontas.")
    print("Suba o painel com:  python cli.py painel")


def _abrir_navegador(porta):
    """Abre a aba assim que a porta atender.

    O Streamlit abriria sozinho, mas só fora do modo headless — e fora dele ele
    também pede um e-mail na primeira execução da máquina, o que trava o
    terminal de quem só queria ver o painel. Headless fica ligado e a aba é
    aberta aqui.
    """
    def esperar():
        for _ in range(60):
            try:
                with socket.create_connection(("127.0.0.1", porta), timeout=0.5):
                    webbrowser.open(f"http://localhost:{porta}")
                    return
            except OSError:
                time.sleep(0.5)

    threading.Thread(target=esperar, daemon=True).start()


def cmd_painel(args):
    alvo = config.RAIZ / "zeki" / "painel" / "app.py"
    porta = args.porta or 8501
    comando = [sys.executable, "-m", "streamlit", "run", str(alvo),
               "--server.port", str(porta)]

    ambiente = dict(os.environ)
    if args.publicado:
        # Força a leitura só da camada ouro, para conferir localmente como a
        # versão publicada se comporta sem a prata.
        ambiente["ZEKI_MODO"] = "publicado"

    if not args.sem_navegador:
        _abrir_navegador(porta)
    raise SystemExit(subprocess.call(comando, env=ambiente))


def main():
    p = argparse.ArgumentParser(prog="zeki", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-v", "--verboso", action="store_true")
    sub = p.add_subparsers(dest="comando", required=True)

    a = sub.add_parser("atualizar", help="baixa da ANEEL o que mudou")
    a.add_argument("--anos", nargs="*", type=int)
    a.add_argument("--amostra", action="store_true",
                   help=f"só {config.ANO_AMOSTRA}, para uma primeira execução rápida")
    a.set_defaults(func=cmd_atualizar)

    c = sub.add_parser("curar", help="normaliza e grava a camada prata")
    c.add_argument("--anos", nargs="*", type=int)
    c.add_argument("--amostra", action="store_true")
    c.add_argument("--so-fato", action="store_true", help="pula as dimensões")
    c.set_defaults(func=cmd_curar)

    k = sub.add_parser("clima", help="ERA5 horário de MG")
    k.add_argument("--ate", help="último mês a baixar, no formato AAAA-MM")
    k.add_argument("--checar", action="store_true",
                   help="só testa credencial e licença do CDS")
    k.set_defaults(func=cmd_clima)

    m = sub.add_parser(
        "amostra",
        help=f"baixa e prepara só {config.ANO_AMOSTRA}, para um primeiro giro",
    )
    m.set_defaults(func=cmd_amostra)

    cc = sub.add_parser("curar-clima",
                        help="ERA5 bruto -> grade, pesos e clima por conjunto")
    cc.set_defaults(func=cmd_curar_clima)

    n = sub.add_parser("mensal",
                       help="baixa o que mudou, cura e regera os agregados")
    n.add_argument("--anos", nargs="*", type=int)
    n.add_argument("--com-ponte", action="store_true",
                   help="refaz também as dimensões a partir da ponte da ANEEL")
    n.add_argument("--com-clima", action="store_true",
                   help="busca no CDS os meses de ERA5 que faltam")
    n.add_argument("--conferir", action="store_true",
                   help="só diz se há novidade; sai com 1 quando há")
    n.set_defaults(func=cmd_mensal)

    v = sub.add_parser("verificar", help="audita a base curada")
    v.set_defaults(func=cmd_verificar)

    b = sub.add_parser("publicar", help="monta a camada ouro para publicação")
    b.set_defaults(func=cmd_publicar)

    d = sub.add_parser("painel", help="sobe o dashboard")
    d.add_argument("--porta", type=int)
    d.add_argument("--publicado", action="store_true",
                   help="simula a versão publicada, lendo só a camada ouro")
    d.add_argument("--sem-navegador", action="store_true",
                   help="não abre a aba automaticamente")
    d.set_defaults(func=cmd_painel)

    args = p.parse_args()
    _log(args.verboso)
    args.func(args)


if __name__ == "__main__":
    main()
