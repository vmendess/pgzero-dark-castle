# Dark Castle

Pequeno jogo de plataforma em Pygame Zero com combate, coleta e vitória por eliminação de inimigos, focado em execução simples para avaliação técnica rigorosa.

## Demo
![Gameplay](docs/gameplay.gif)

## Requisitos
- Python 3.x
- Pygame Zero (pgzero)

## Instalação
~~~bash
pip install pgzero
~~~

## Execução
~~~bash
pgzrun main.py
~~~
- Estrutura esperada: mantenha `images/`, `sounds/` e `music/` ao lado do arquivo de entrada para que o carregamento automático funcione.

## Controles
- Movimento: WASD
- Pulo: Espaço/W/↑
- Dash: Shift
- Ataque: Mouse esquerdo
- Escudo: Mouse direito
- Usar portas: E
- Pausa: Esc

## Estrutura de pastas
~~~text
images/   # sprites e UI
sounds/   # efeitos (.wav)
music/    # trilhas (.mp3)
docs/     # GIFs/screenshots usados no README
main.py   # arquivo principal de execução na IDE
main.pyi  # pode ignorar
~~~

~~~python
# Este repositório é licenciado sob MIT.
# Leia o arquivo LICENSE na raiz para os termos completos.
~~~
