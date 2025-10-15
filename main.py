# DARK CASTLE - Jogo de Plataforma

# Nota de manutenção: Apenas comentários adicionais foram inseridos; nenhuma linha de lógica foi alterada.
# O objetivo é explicar termos técnicos, decisões de design e a razão por trás de funções e estados,
# mantendo o estilo de comentários já usado neste arquivo.


# ESTRUTURA DE PASTAS NECESSÁRIA:
# /sounds/         - Efeitos sonoros (.wav).
# /music/          - Músicas de fundo (.mp3).
# /images/         - Sprites e gráficos (.png).

"""
PgZero disponibiliza objetos como screen, keyboard, keys, music, sounds e clock como nomes globais quando o jogo é executado via pgzrun, 
mas eles não são módulos ou símbolos importáveis que existam antes da execução, o que confunde verificadores estáticos como 
Pylance. Há um histórico de issues em Pyright onde projetos PgZero recebem “reportUndefinedVariable”, confirmando que não é um erro 
de lógica, mas uma limitação da análise estática com esse framework, basicamente a diretiva abaixo silencia avisos falsos-positivos 
sobre variáveis globais do PgZero (ex.: screen, keyboard). Esses nomes são injetados pelo runtime do pgzrun em tempo 
de execução e, por isso, não são importados manualmente.
"""
# pyright: reportUndefinedVariable=false

# --- Importações ---
import pgzrun                     # Inicializa o loop de jogo do PgZero (pgzrun.go()).
from pgzero.actor import Actor    # Representa sprites com posição, imagem e retângulo de colisão.
from pgzero.keyboard import keys  # Enum de teclas para eventos/input.
from pgzero.rect import Rect      # Retângulos para colisão/hitboxes.
import math
import random


# --- Configurações Globais ---
WIDTH, HEIGHT, TITLE = 800, 600, "Dark Castle"  # Tamanho da janela e título exibido na barra do jogo.


# --- Constantes de Física ---
# Governam o comportamento e movimento das entidades no jogo.
# GRAVITY: aceleração aplicada verticalmente a cada frame (unidade em pixels/frame^2).
# JUMP_STRENGTH: velocidade inicial ao pular (negativa = para cima).
# PLAYER_SPEED: velocidade horizontal base do jogador.
# DASH_SPEED/DASH_DURATION: velocidade e duração (em frames) do dash, respectivamente.
# ENEMY_SPEED: velocidade de caminhada dos inimigos.
GRAVITY = 0.5
JUMP_STRENGTH = -11.4
PLAYER_SPEED = 1.56
DASH_SPEED = 10
DASH_DURATION = 15
ENEMY_SPEED = 0.9


# --- Estados do Jogo ---
# Define os diferentes estados do jogo para controlar telas e lógicas.
# MENU: tela inicial; PLAYING: jogando; GAME_OVER: derrota; VICTORY: vitória; PAUSED: pausa; STARTING: transição de início.
MENU, PLAYING, GAME_OVER, VICTORY, PAUSED, STARTING = 0, 1, 2, 3, 4, 5


# --- Tamanho do Titulo ---
TILE_SIZE = 32  # Tamanho (em pixels) de cada tile gráfico no cenário (padrão 32x32).


# CLASSE BASE PARA ENTIDADES ANIMADAS
class AnimatedEntity:
    """
    Classe base para entidades com animação de sprite.
    Gerencia frames, estados ('idle', 'run', etc.) e direção.
    """
    def __init__(self, x, y, animations_right, animations_left):
        # animations_right/left: dict estado -> lista de frames (nomes de imagens).
        # current_state: estado de animação atual; facing_right: direção visual do sprite; frame/frame_counter: controle de ciclos.
        self.animations_right, self.animations_left = animations_right, animations_left
        self.current_state = list(animations_right.keys())[0]
        self.facing_right = True
        self.frame, self.frame_counter = 0, 0
        self.frame_speeds = {'idle': 6, 'default': 5}
        self.actor = Actor(list(animations_right.values())[0][0], pos=(x, y))  # Usa o primeiro frame do primeiro estado como imagem inicial.

    def animate(self):
        """Atualiza o frame da animação a cada ciclo do jogo."""
        # frame_speed controla a "lentidão" do avanço de frames para cada estado.
        frame_speed = self.frame_speeds.get(self.current_state, self.frame_speeds['default'])
        self.frame_counter += 1
        if self.frame_counter >= frame_speed:
            self.frame_counter = 0
            # Seleciona a lista de frames conforme a direção (direita/esquerda) e estado atual.
            anim = (self.animations_right if self.facing_right else self.animations_left).get(self.current_state)
            if anim:
                # Em 'shield', a animação trava no último frame (postura de defesa mantida).
                if self.current_state == 'shield' and self.frame == len(anim) - 1: return
                self.frame = (self.frame + 1) % len(anim)
                self.actor.image = anim[self.frame]

    def draw(self): self.actor.draw()  # Encapsula o draw do Actor para manter a interface das entidades.


# CLASSES DE DECORAÇÃO E INTERAÇÃO
class AnimatedDecoration(AnimatedEntity):
    """Entidade para decorações animadas sem colisão."""
    def __init__(self, x, y, anim_frames, frame_speed=10):
        # Decorações reaproveitam a infraestrutura de animação, mas não interagem fisicamente.
        super().__init__(x, y, {'anim': anim_frames}, {'anim': anim_frames})
        self.frame_speeds, self.current_state = {'anim': frame_speed, 'default': frame_speed}, 'anim'
    def update(self): self.animate()  # Decorações apenas animam (não têm lógica de jogo).

class Door:
    """Objeto de porta que teleporta o jogador."""
    def __init__(self, x, y, dest_x, dest_y, image_name='cenario/porta'):
        # bottomleft: posiciona a base da sprite da porta sobre o tile superior do piso.
        self.actor = Actor(image_name, bottomleft=(x, y))
        self.destination = (dest_x, dest_y)  # Posição de saída (teleporte).
    def draw(self): self.actor.draw()

class Collectible(AnimatedDecoration):
    """Itens colecionáveis que adicionam pontos ao score."""
    def __init__(self, x, y, anim_frames, value=10):
        super().__init__(x, y, anim_frames, 12)
        self.collected, self.value = False, value  # collected previne coleta múltipla; value incrementa o placar.

class Trap:
    """Armadilhas estáticas que causam a morte do jogador."""
    def __init__(self, x, y, image_name):
        self.actor = Actor(image_name, topleft=(x, y))  # topleft facilita alinhar a armadilha à grade.
    def draw(self): self.actor.draw()


# CLASSE DO JOGADOR (KNIGHT)
class Knight(AnimatedEntity):
    """Controla toda a lógica do jogador: movimento, física, ações e estado."""
    def __init__(self, x, y):
        # Mapeia nome do estado -> quantidade de frames de animação.
        animations = {'idle': 15, 'run': 8, 'jump_and_fall': 12, 'attack': 22, 'death': 15, 'roll': 15, 'shield': 7}
        super().__init__(
            x, y,
            {k: [f'knight_{k}/{i}' for i in range(v)] for k, v in animations.items()},
            {k: [f'knight_{k}_left/{i}' for i in range(v)] for k, v in animations.items()}
        )
        self.actor.anchor = ('center', 'bottom')  # Âncora no centro/base facilita colisões com piso.
        self.frame_speeds = {'idle': 5, 'run': 4, 'attack': 1.8, 'shield': 2, 'roll': 4, 'default': 5}

        # Componentes de movimento/física:
        self.vx, self.vy, self.on_ground = 0, 0, False

        # Vida/estado:
        self.health, self.is_alive = 3, True

        # Ações e travas (state machine de ação):
        self.is_attacking, self.is_dashing, self.is_shielding = False, False, False
        self.attack_frame_counter, self.dash_counter, self.dash_cooldown = 0, 0, 0
        self.invulnerable_timer, self.death_timer = 0, 0  # Invulnerabilidade temporária e temporizador de morte.

        # Placar e controle de golpes:
        self.score, self.hit_enemies_this_attack, self.jumps_left, self.animation_locked = 0, [], 1, False

        # Qualidade de controle no pulo:
        self.coyote_time, self.coyote_frames = 0, 6         # “Coyote time”: janela após sair da borda ainda permitindo pular.
        self.jump_buffer, self.jump_buffer_frames = 0, 8     # “Jump buffer”: armazena o comando de pulo por alguns frames.

        # “Hitstop” suaviza impacto de golpes; controle de eventos de solo e som de passos:
        self.hitstop_timer, self.was_on_ground, self.last_walk_frame = 0, False, -1

    def update(self, platforms, traps, collectibles):
        """Lógica principal do jogador, executada a cada frame para atualizar seu estado."""
        # 1) Estados terminais/temporários que interrompem a lógica:
        if not self.is_alive:
            # Animação de morte toca até o último frame e congela.
            if self.frame < 14: self.animate()
            else: self.frame = 14
            self.death_timer += 1; return
        if self.hitstop_timer > 0: self.hitstop_timer -= 1; return  # Breve parada quando o golpe acerta algo (feedback).
        if self.invulnerable_timer > 0: self.invulnerable_timer -= 1  # Piscar/ignorar dano por alguns frames.
        if self.dash_cooldown > 0: self.dash_cooldown -= 1

        # 2) Janelas de controle do pulo (coyote/jump buffer):
        if self.on_ground: self.coyote_time = self.coyote_frames
        elif self.coyote_time > 0: self.coyote_time -= 1
        if self.jump_buffer > 0:
            self.jump_buffer -= 1
            # Se voltou ao chão antes do buffer expirar, consome o comando e pula.
            if (self.on_ground or self.coyote_time > 0) and not any([self.is_attacking, self.is_dashing, self.is_shielding]):
                self.jump(); self.jump_buffer = 0

        # 3) Máquina de Estados de Ação (prioridades: shield > dash > attack > movimento):
        if self.is_shielding: self.vx, self.animation_locked = 0, True
        elif self.is_dashing:
            self.dash_counter += 1; self.vx = DASH_SPEED * (1 if self.facing_right else -1); self.animation_locked = True
            if self.dash_counter >= DASH_DURATION: self.is_dashing, self.vx, self.animation_locked = False, 0, False
        elif self.is_attacking: self.vx, self.animation_locked = 0, True; self.update_attack()
        else:
            # Movimento lateral básico (A/← e D/→), apenas quando não está realizando ações que travam animação.
            self.animation_locked = False
            if keyboard.left or keyboard.a: self.vx, self.facing_right = -PLAYER_SPEED, False
            elif keyboard.right or keyboard.d: self.vx, self.facing_right = PLAYER_SPEED, True
            else: self.vx = 0
            if (keyboard.lshift or keyboard.rshift) and self.dash_cooldown == 0 and not self.is_dashing: self.start_dash()

        # 4) Colisão Horizontal (move e resolve empurrando para fora do bloco):
        self.actor.x += self.vx
        for platform in platforms:
            if self.actor.colliderect(platform):
                if self.vx > 0:
                    self.actor.right = platform.left
                    if self.is_dashing: self.is_dashing, self.vx, self.animation_locked = False, 0, False  # Dash interrompido ao colidir.
                elif self.vx < 0:
                    self.actor.left = platform.right
                    if self.is_dashing: self.is_dashing, self.vx, self.animation_locked = False, 0, False

        # 5) Gravidade e Colisão Vertical:
        self.was_on_ground, self.on_ground = self.on_ground, False
        self.vy += GRAVITY; self.actor.y += self.vy
        if self.actor.top < 30: self.actor.top, self.vy = 30, 0  # Limita a altura mínima (forro).
        for platform in platforms:
            if self.actor.colliderect(platform):
                if self.vy > 0:
                    # Aterrisagem: corrige posição, zera vy e restaura pulo duplo (jumps_left).
                    self.actor.bottom, self.on_ground, self.jumps_left, self.vy = platform.top, True, 1, 0
                    if not self.was_on_ground: play_sound('knight_land', 0.15)
                    break
                elif self.vy < 0:
                    self.actor.top = platform.bottom
                    # Empurra levemente para baixo para evitar “túnel” (atravessar o teto em alta velocidade).
                    self.vy = 1
                    break

        # 6) Interações com o ambiente (traps/collectibles/quedas fora da tela):
        if not self.is_dashing:
            for trap in traps:
                if self.actor.colliderect(trap.actor): self.die()  # Traps matam instantaneamente.
        for collectible in collectibles:
            if not collectible.collected and self.actor.colliderect(collectible.actor):
                collectible.collected, self.score = True, self.score + collectible.value; play_sound('collectible_get')
        if self.actor.top > HEIGHT + 50: self.die()  # Caiu no “void”.

        # 7) Seleção de animação (somente quando não está “travado” por uma ação):
        if not self.animation_locked:
            if not self.on_ground: self.current_state, self.last_walk_frame = 'jump_and_fall', -1
            elif abs(self.vx) > 0:
                self.current_state = 'run'
                # Efeito sonoro de passos sincronizado com frames-chave da animação.
                if self.frame in [0, 4] and self.frame != self.last_walk_frame: play_sound('knight_walk', 1.0); self.last_walk_frame = self.frame
            else: self.current_state, self.last_walk_frame = 'idle', -1
        elif self.is_dashing: self.current_state = 'roll'
        elif self.is_shielding: self.current_state = 'shield'
        self.animate()  # Aplica a animação conforme o estado/direção atual.

    def jump(self):
        """Executa a ação de pular se as condições permitirem."""
        # Pulo permitido se: ainda houver jumps_left, estiver no coyote time, e não estiver atacando/dando dash/defendendo.
        if (self.jumps_left > 0 or self.coyote_time > 0) and not any([self.is_attacking, self.is_dashing, self.is_shielding]):
            self.vy = JUMP_STRENGTH; play_sound('knight_jump', 1.0)
            if self.coyote_time > 0: self.coyote_time = 0
            else: self.jumps_left -= 1
            if not self.animation_locked: self.frame, self.current_state = 0, 'jump_and_fall'

    def start_attack(self):
        """Inicia a sequência de ataque."""
        # Ataques travam a movimentação e rodam a animação completa; enemies atingidos são lembrados para evitar hits múltiplos no mesmo golpe.
        if not any([self.is_attacking, self.is_dashing, self.is_shielding]):
            self.is_attacking, self.current_state, self.frame, self.animation_locked = True, 'attack', 0, True
            self.hit_enemies_this_attack = []; play_sound('knight_attack_swing', 1.0)

    def start_dash(self):
        """Inicia a esquiva (dash), que concede invulnerabilidade."""
        # Dash aplica velocidade constante por DASH_DURATION frames; entra em cooldown para evitar “spam”.
        if not self.is_attacking and not self.is_shielding:
            self.is_dashing, self.dash_counter, self.dash_cooldown = True, 0, 60
            self.invulnerable_timer, self.animation_locked = DASH_DURATION, True
            play_sound('knight_roll', 0.3)

    def start_shield(self):
        """Levanta o escudo para bloquear dano."""
        # Enquanto o escudo está ativo, não há movimento horizontal e golpes inimigos não causam dano (som de bloqueio).
        if not self.is_attacking and not self.is_dashing:
            self.is_shielding, self.frame, self.animation_locked = True, 0, True; play_sound('knight_shield_up', 1.0)

    def stop_shield(self):
        # Ao soltar o botão, sai do estado de defesa; interrompe som contínuo caso esteja ativo.
        if self.is_shielding: self.is_shielding, self.animation_locked = False, False; stop_sound('knight_shield_blocked')

    def update_attack(self):
        # Ao chegar ao fim da animação de ataque (último frame), libera o controle e reseta a lista de inimigos já atingidos.
        anims = self.animations_right if self.facing_right else self.animations_left
        if self.frame == len(anims['attack']) - 1 and self.frame_counter >= self.frame_speeds['attack'] - 1:
            self.is_attacking, self.animation_locked = False, False; self.hit_enemies_this_attack.clear()

    def take_damage(self, amount=1):
        # Ignora dano se invulnerável, morto ou bloqueando com escudo (toca som de bloqueio).
        if self.invulnerable_timer > 0 or not self.is_alive: return
        if self.is_shielding: stop_sound('knight_shield_blocked'); play_sound('knight_shield_blocked', 1.0, max_duration=0.3); return
        self.health -= amount; play_sound('knight_hurt', volume=0.6)
        if self.health <= 0: self.die()
        else: self.invulnerable_timer = 60  # Janela de invulnerabilidade pós-dano.

    def die(self):
        # Entra no estado de morte: anima, para música e toca trilha de game over.
        if not self.is_alive: return
        self.is_alive, self.health = False, 0
        self.current_state, self.frame, self.death_timer, self.animation_locked = 'death', 0, 0, True
        play_sound('knight_death'); stop_music(); play_music('game_over', loops=0)

    def get_attack_hitbox(self):
        # Retorna um Rect representando a área do golpe em frames específicos da animação (janela ativa do ataque).
        if self.is_attacking and 5 <= self.frame <= 10: return Rect(self.actor.x + (18 if self.facing_right else -63), self.actor.y - 30, 45, 40)
        return None


# SKELETON ENEMY CLASS
class Skeleton(AnimatedEntity):
    """Controla a IA, movimento e ataques do inimigo Esqueleto."""
    def __init__(self, x, y, patrol_left, patrol_right):
        animations = {'idle': 8, 'walk': 10, 'attack': 10, 'die': 13}
        super().__init__(x, y, {k: [f'skeleton_{k}/{i}' for i in range(v)] for k, v in animations.items()}, {k: [f'skeleton_{k}_left/{i}' for i in range(v)] for k, v in animations.items()})
        self.actor.anchor = ('center', 'bottom')
        # Patrol: limites horizontais de patrulha; detection_radius: distância para começar a perseguir/atacar.
        self.patrol_left, self.patrol_right = patrol_left, patrol_right
        self.speed, self.detection_radius = ENEMY_SPEED, 250
        self.vy, self.on_ground = 0, False
        self.health, self.is_alive, self.is_attacking = 2, True, False
        self.attack_cooldown, self.death_animation_timer, self.despawn_ready = 0, 0, False
        self.patrol_direction, self.stuck_timer, self.last_x, self.initialized_position = 1, 0, x, False  # initialized_position garante que ele "caia" até o piso antes de ativar IA.

    def update(self, player, platforms):
        """Lógica principal do inimigo, executada a cada frame."""
        # 1) Fase de inicialização: deixa o esqueleto “cair” até um piso antes de começar a patrulha/IA.
        if not self.initialized_position:
            self.vy += GRAVITY; self.actor.y += self.vy
            for platform in platforms:
                if self.actor.colliderect(platform) and self.vy > 0:
                    self.actor.bottom, self.on_ground, self.vy, self.initialized_position = platform.top, True, 0, True; break
            self.animate(); return

        # 2) Estados de morte/remoção:
        if not self.is_alive:
            if self.frame < 12: self.animate()
            else: self.frame = 12
            self.death_animation_timer += 1
            # Aguarda tocar toda a animação + um atraso, depois marca para remoção.
            if self.death_animation_timer >= 13 * self.frame_speeds['default'] + 60: self.despawn_ready = True
            return

        # 3) Cooldown de ataque:
        if self.attack_cooldown > 0: self.attack_cooldown -= 1

        # 4) Percepção do jogador e decisão de movimento/ataque:
        distance_to_player, vertical_distance, vx = self.actor.distance_to(player.actor), abs(self.actor.y - player.actor.y), 0
        if self.is_attacking: self.update_attack()
        elif distance_to_player < self.detection_radius and player.is_alive and vertical_distance < 80:
            self.current_state = 'walk'
            if distance_to_player < 70 and self.attack_cooldown == 0: self.facing_right = player.actor.x > self.actor.x; self.start_attack()
            else:
                # Caminha na direção do jogador respeitando limites de patrulha.
                if player.actor.x > self.actor.x and self.actor.x < self.patrol_right: vx, self.facing_right = self.speed, True
                elif player.actor.x < self.actor.x and self.actor.x > self.patrol_left: vx, self.facing_right = -self.speed, False
        else:
            # Patrulha “ping-pong” entre patrol_left e patrol_right quando o jogador está fora de alcance.
            self.current_state = 'idle'
            if not self.is_attacking:
                if self.patrol_direction == 1 and self.actor.x >= self.patrol_right: self.patrol_direction, self.facing_right = -1, False
                elif self.patrol_direction == -1 and self.actor.x <= self.patrol_left: self.patrol_direction, self.facing_right = 1, True

        # 5) Detecção de “travamento” (esbarrando em algo por muito tempo) e inversão provisória de direção:
        if abs(self.actor.x - self.last_x) < 0.1 and vx != 0:
            self.stuck_timer += 1
            if self.stuck_timer > 30: self.patrol_direction *= -1; self.facing_right = not self.facing_right; self.stuck_timer = 0
        else: self.stuck_timer = 0

        # 6) Movimento horizontal com correção de empurrão contra o jogador e plataformas:
        self.last_x, old_x = self.actor.x, self.actor.x; self.actor.x += vx
        if player.is_alive and self.actor.colliderect(player.actor):
            self.actor.x = old_x
            if not self.is_attacking and self.attack_cooldown == 0 and distance_to_player < 70:
                self.facing_right = player.actor.x > self.actor.x; self.start_attack()
        for platform in platforms:
            if self.actor.colliderect(platform):
                if vx > 0: self.actor.right, self.patrol_direction = platform.left, -1
                elif vx < 0: self.actor.left, self.patrol_direction = platform.right, 1
        if not self.is_attacking and self.current_state == 'walk' and abs(self.actor.x - old_x) < 0.1 and vx != 0: self.current_state = 'idle'

        # 7) Gravidade e colisão vertical:
        self.on_ground = False; self.vy += GRAVITY; self.actor.y += self.vy
        for platform in platforms:
            if self.actor.colliderect(platform):
                if self.vy > 0: self.actor.bottom, self.on_ground, self.vy = platform.top, True, 0; break
                elif self.vy < 0: self.actor.top, self.vy = platform.bottom, 0; break

        # 8) “Failsafe”: se cair fora da tela, volta ao spawn original e reinicializa fase de queda.
        if self.actor.top > HEIGHT + 50: self.actor.x, self.actor.y, self.vy, self.initialized_position = self.original_spawn_pos[0], self.original_spawn_pos[1], 0, False
        self.animate()

    def start_attack(self): self.is_attacking, self.current_state, self.frame, self.attack_cooldown = True, 'attack', 0, 120  # Ataque tem janela ativa e entra em cooldown após iniciar.

    def update_attack(self):
        # Ao fim dos frames da animação de ataque, libera para voltar a andar/patrulhar.
        if self.frame == len(self.animations_right['attack']) - 1: self.is_attacking = False

    def take_damage(self, amount=1):
        # Reduz vida; se zerar, entra em estado de morte (com som/anim).
        if self.is_alive: self.health -= amount;
        if self.health <= 0: self.die()

    def die(self):
        self.is_alive, self.current_state, self.frame, self.death_animation_timer = False, 'die', 0, 0
        play_sound('skeleton_die', volume=0.7)

    def get_attack_hitbox(self):
        # Hitbox de ataque do esqueleto: retângulo à frente por alguns frames da animação (janela ativa).
        if self.is_attacking and 3 <= self.frame <= 6: return Rect(self.actor.x + (16 if self.facing_right else -40), self.actor.y - 25, 24, 30)
        return None

# INICIALIZAÇÃO E VARIÁVEIS GLOBAIS
menu_screen = 'main'
try: menu_background = Actor('oig3', pos=(WIDTH / 2, HEIGHT / 2))
except: menu_background = None  # Se a imagem do menu não existir, cai para um fundo sólido.
mouse_pos, menu_animation_offset = (0, 0), 0
sound_enabled, music_enabled, current_shield_sound = True, True, None  # Toggles globais de áudio.
# Paleta de cores para UI/HUD:
DARK_PURPLE, MID_PURPLE, BRIGHT_PURPLE = (25, 15, 35), (75, 45, 95), (130, 80, 160)
LIGHT_PURPLE, GOLD, WHITE, DARK_OVERLAY = (180, 140, 220), (255, 215, 0), (255, 255, 255), (0, 0, 0, 180)
# Geometria dos botões do menu:
BUTTON_WIDTH, BUTTON_HEIGHT, BUTTON_SPACING = 280, 55, 20
button_start = Rect((WIDTH - BUTTON_WIDTH) / 2, 230, BUTTON_WIDTH, BUTTON_HEIGHT)
button_sound = Rect((WIDTH - BUTTON_WIDTH) / 2, 230 + BUTTON_HEIGHT + BUTTON_SPACING, BUTTON_WIDTH, BUTTON_HEIGHT)
button_exit = Rect((WIDTH - BUTTON_WIDTH) / 2, 230 + 2 * (BUTTON_HEIGHT + BUTTON_SPACING), BUTTON_WIDTH, BUTTON_HEIGHT)
game_state = MENU
platforms, decorations, traps, collectibles, enemies, doors, knight = [], [], [], [], [], [], None
hearts = [Actor('vida_do_jogador/0', topleft=(10 + i * 40, 10)) for i in range(3)]  # HUD de vida (3 corações).
victory_timer, start_delay_timer, MAX_START_DELAY = None, 0, 45  # start_delay controla fade-in de música/jogo ao iniciar.

# SISTEMA DE SOM E MÚSICA
def play_sound(sound_name, volume=1.0, max_duration=None):
    """Toca um efeito sonoro da pasta /sounds."""
    # Alguns sons são normalizados para volumes menores/maiores para mixagem consistente.
    # current_shield_sound garante que o som de bloqueio não acumule toques simultâneos (stop antes de tocar novamente).
    global current_shield_sound
    if not sound_enabled: return
    try:
        sound_to_play = getattr(sounds, sound_name)
        if sound_name == 'knight_shield_blocked' and current_shield_sound:
            try: current_shield_sound.stop()
            except: pass
        if sound_name in ['knight_walk', 'knight_jump', 'knight_attack_swing', 'knight_shield_up', 'knight_shield_blocked']: volume *= 0.1
        elif sound_name in ['menu_click', 'menu_select']: volume *= 2.0
        sound_to_play.set_volume(volume); sound_to_play.play()
        if sound_name == 'knight_shield_blocked':
            current_shield_sound = sound_to_play
            # max_duration evita que o som de bloqueio fique tocando indefinidamente se algo sair de sincronia.
            if max_duration: clock.schedule_unique(lambda: stop_sound(sound_name), max_duration)
    except AttributeError: print(f"ERRO: Som '{sound_name}' não encontrado. Verifique se o arquivo está na pasta /sounds/.")
    except Exception as e: print(f"Erro inesperado ao tocar som '{sound_name}': {e}")

def stop_sound(sound_name):
    # Interrompe especificamente o som contínuo de bloqueio de escudo.
    global current_shield_sound
    if sound_name == 'knight_shield_blocked' and current_shield_sound:
        try: current_shield_sound.stop(); current_shield_sound = None
        except: pass

def play_music(music_name, loops=-1):
    # Toca música de fundo da pasta /music; loops=-1 repete, loops=0 toca uma vez.
    if music_enabled:
        try:
            if loops == -1: music.play(music_name)
            else: music.play_once(music_name)
            # Volume base: menu mais baixo, gameplay um pouco mais alto.
            music.set_volume(0.15 if music_name == 'menu_music' else 0.3)
        except Exception as e: print(f"Erro ao tocar música {music_name}: {e}")

def stop_music():
    # Tenta parar a música atual (ignora erro se nada estiver tocando).
    try: music.stop()
    except: pass

def build_level():
    """Cria e posiciona todos os elementos estáticos do cenário."""
    # Estrutura básica: teto, pisos principais (piso1) e plataformas elevadas (piso2).
    # Também adiciona paredes laterais invisíveis para conter o jogador/esqueletos (Rect).
    global platforms, decorations, traps, collectibles, doors
    platforms, decorations, traps, collectibles, doors = [],[],[],[],[]

    # Teto
    for i in range(25): platforms.append(Actor('cenario/teto', topleft=(i*TILE_SIZE, 0)))
    platforms.append(Rect(0, -10, WIDTH, 10))  # Borda sólida acima do teto gráfico (evita “clipping”).

    # Piso principal (esquerda e direita)
    for i in range(0, 8): platforms.append(Actor('cenario/piso1', topleft=(i*TILE_SIZE, HEIGHT-TILE_SIZE)))
    for i in range(17, 25): platforms.append(Actor('cenario/piso1', topleft=(i*TILE_SIZE, HEIGHT-TILE_SIZE)))

    # Paredes laterais invisíveis (colisão)
    platforms.append(Rect((-10, 0), (10, HEIGHT))); platforms.append(Rect((WIDTH, 0), (10, HEIGHT)))

    # Plataformas elevadas (piso2): níveis superiores do cenário
    for i in range(18, 24): platforms.append(Actor('cenario/piso2', topleft=(i*TILE_SIZE, 160)))
    for i in range(18, 24): platforms.append(Actor('cenario/piso2', topleft=(i*TILE_SIZE, 64)))
    for i in range(3, 5): platforms.append(Actor('cenario/piso2', topleft=(576, i*TILE_SIZE)))
    platforms.append(Actor('cenario/piso2', topleft=(736, 96))); platforms.append(Actor('cenario/piso2', topleft=(736, 128)))
    for i in range(6): platforms.append(Actor('cenario/piso2', topleft=(128+i*TILE_SIZE, 450)))
    for i in range(7): platforms.append(Actor('cenario/piso2', topleft=(480+i*TILE_SIZE, 380)))
    for i in range(3): platforms.append(Actor('cenario/piso2', topleft=(352+i*TILE_SIZE, 300)))
    for i in range(2): platforms.append(Actor('cenario/piso2', topleft=(224+i*TILE_SIZE, 220)))

    # Portas e destinos de teleporte (duas vias)
    doors.append(Door(500, 380, 710, 160)); doors.append(Door(700, 160, 520, 380, image_name='cenario/porta_left'))

    # Decorações estruturais (colunas laterais para dar profundidade visual)
    for i in range(0, 18):
        decorations.append(AnimatedDecoration(16, i*TILE_SIZE+16, ['cenario/coluna'], 999))
        decorations.append(AnimatedDecoration(WIDTH-16, i*TILE_SIZE+16, ['cenario/coluna'], 999))

    # Tochas animadas (luzes do cenário)
    torch_frames = [f'cenario/tochas/{j}' for j in range(3)]
    decorations.extend([
        AnimatedDecoration(140, 420, torch_frames, 10), AnimatedDecoration(340, 420, torch_frames, 10),
        AnimatedDecoration(492, 350, torch_frames, 10), AnimatedDecoration(692, 350, torch_frames, 10),
        AnimatedDecoration(364, 270, torch_frames, 10), AnimatedDecoration(428, 270, torch_frames, 10),
        AnimatedDecoration(236, 190, torch_frames, 10), AnimatedDecoration(268, 190, torch_frames, 10),
        AnimatedDecoration(588, 130, torch_frames, 10), AnimatedDecoration(732, 130, torch_frames, 10),
        AnimatedDecoration(660, 46, torch_frames, 10),
        AnimatedDecoration(50, 538, torch_frames, 10), AnimatedDecoration(200, 538, torch_frames, 10),
        AnimatedDecoration(600, 538, torch_frames, 10), AnimatedDecoration(750, 538, torch_frames, 10)
    ])

    # Outras decorações de ambiente (bandeiras, correntes, janelas, etc.)
    decorations.extend([
        AnimatedDecoration(200, 100, ['cenario/bandeira'], 999),
        AnimatedDecoration(600, 180, ['cenario/bandeira'], 999),
        AnimatedDecoration(WIDTH - 200, 100, ['cenario/bandeira'], 999),
        AnimatedDecoration(320, 40, ['cenario/correntes'], 999),
        AnimatedDecoration(480, 40, ['cenario/correntes'], 999),
        AnimatedDecoration(180, 420, ['cenario/detalhe_parede1'], 999),
        AnimatedDecoration(560, 350, ['cenario/detalhe_parede2'], 999),
        AnimatedDecoration(396, 270, ['cenario/detalhe_parede1'], 999),
        AnimatedDecoration(100, 300, ['cenario/janela'], 999),
        AnimatedDecoration(700, 300, ['cenario/janela'], 999)
    ])

    # Colecionáveis (diamantes) distribuídos por plataformas e áreas de risco/alcance
    diamond_frames = [f'cenario/diamantes/{i}' for i in range(6)]
    collectibles.extend([
        Collectible(190, 420, diamond_frames, 10), Collectible(290, 420, diamond_frames, 10),
        Collectible(400, 270, diamond_frames, 10), Collectible(540, 350, diamond_frames, 15),
        Collectible(640, 350, diamond_frames, 15), Collectible(250, 190, diamond_frames, 15),
        Collectible(120, 538, diamond_frames, 10), Collectible(680, 538, diamond_frames, 10),
        Collectible(640, 130, diamond_frames, 30), Collectible(660, 130, diamond_frames, 30),
        Collectible(710, 130, diamond_frames, 30), Collectible(635, 40, diamond_frames, 40),
        Collectible(685, 40, diamond_frames, 40)
    ])

# FUNÇÕES DE DESENHO (DRAW)
def draw():
    """Roteador principal de desenho, chamado a cada frame."""
    # Encaminha para a função de tela conforme o estado atual do jogo.
    screen.clear()
    if game_state == MENU: draw_menu()
    elif game_state == STARTING: draw_starting()
    elif game_state == PLAYING: draw_game()
    elif game_state == PAUSED: draw_paused()
    elif game_state == GAME_OVER: draw_game_over()
    elif game_state == VICTORY: draw_victory()

def draw_menu():
    # Desenha o fundo do menu (imagem se existir, caso contrário cor sólida) e uma camada escurecida (overlay).
    global menu_animation_offset
    if menu_background: menu_background.draw()
    else: screen.fill((10, 5, 15))
    screen.draw.filled_rect(Rect(0, 0, WIDTH, HEIGHT), DARK_OVERLAY)

    # Animação sutil do título (senoidal) para dar vida à tela.
    menu_animation_offset = (menu_animation_offset + 0.03) % (2 * math.pi)
    title_y = 100 + math.sin(menu_animation_offset) * 5

    # Título com “camadas” para efeito de sombra/brilho.
    screen.draw.text("DARK CASTLE", center=(WIDTH / 2 + 4, title_y + 4), fontsize=80, color=DARK_PURPLE)
    screen.draw.text("DARK CASTLE", center=(WIDTH / 2 + 2, title_y + 2), fontsize=80, color=MID_PURPLE)
    screen.draw.text("DARK CASTLE", center=(WIDTH / 2, title_y), fontsize=80, color=WHITE, owidth=2, ocolor=BRIGHT_PURPLE)
    screen.draw.text("Uma Aventura nas Trevas", center=(WIDTH / 2, title_y + 55), fontsize=20, color=LIGHT_PURPLE, owidth=0.5, ocolor=DARK_PURPLE)

    # Botões interativos e texto de controles.
    if menu_screen == 'main':
        draw_button(button_start, "COMEÇAR O JOGO", "⚔")
        sound_status = "LIGADOS" if (sound_enabled and music_enabled) else "DESLIGADOS"
        sound_icon = "🔊" if (sound_enabled and music_enabled) else "🔇"
        draw_button(button_sound, f"MÚSICA E SONS: {sound_status}", sound_icon)
        draw_button(button_exit, "SAIR", "✖")

        # Guia de controles (resumo):
        controls_y_start = button_exit.bottom + BUTTON_SPACING + 10
        screen.draw.text("CONTROLES", center=(WIDTH / 2, controls_y_start), fontsize=24, color=GOLD, owidth=1, ocolor=DARK_PURPLE)
        controls_text = ["WASD - Mover | ESPAÇO/W/↑ - Pular", "CLICK ESQUERDO - Atacar | CLICK DIREITO - Defender", "SHIFT - Dash | E - Usar Porta | ESC - Pausar"]
        for i, text in enumerate(controls_text): screen.draw.text(text, center=(WIDTH / 2, controls_y_start + 30 + i * 22), fontsize=16, color=LIGHT_PURPLE)
        screen.draw.text("v1.0 | Criado com Pygame Zero", center=(WIDTH / 2, HEIGHT - 20), fontsize=16, color=(150, 150, 150))

def draw_button(rect, text, icon=""):
    # Efeito hover: leve “glow” e borda reforçada; fonte cresce um pouco.
    is_hover = rect.collidepoint(mouse_pos)
    if is_hover:
        hover_rect, bg_color, text_color, border_color, border_width = rect.inflate(8, 4), BRIGHT_PURPLE, WHITE, GOLD, 3
        screen.draw.filled_rect(hover_rect.inflate(-4, -2), (200, 160, 255, 100))
    else:
        hover_rect, bg_color, text_color, border_color, border_width = rect, MID_PURPLE, LIGHT_PURPLE, BRIGHT_PURPLE, 2
    screen.draw.filled_rect(hover_rect, bg_color)
    for i in range(border_width): screen.draw.rect(hover_rect.inflate(i * 2, i * 2), border_color)
    screen.draw.rect(hover_rect.inflate(-6, -6), (255, 255, 255, 50))
    font_size = 26
    if is_hover: font_size = 27 if len(text) > 15 else 28
    icon_pos = (hover_rect.left + 35, hover_rect.centery)
    text_pos = (hover_rect.centerx, hover_rect.centery)
    screen.draw.text(icon, center=icon_pos, fontsize=font_size, color=text_color, owidth=1 if is_hover else 0.5, ocolor=DARK_PURPLE)
    screen.draw.text(text, center=text_pos, fontsize=font_size, color=text_color, owidth=1 if is_hover else 0.5, ocolor=DARK_PURPLE)

def draw_starting():
    # Tela de jogo com fade-in (preto transparente por cima), sincronizado com start_delay_timer.
    draw_game()
    alpha = 255 - (start_delay_timer / MAX_START_DELAY) * 255
    screen.draw.filled_rect(Rect(0, 0, WIDTH, HEIGHT), (0, 0, 0, 255 - alpha))

def draw_game():
    # Desenha cenário, decorações, armadilhas, portas e entidades vivas, além do HUD.
    screen.fill((0, 0, 0))
    for element in platforms + decorations + traps + doors:
        if isinstance(element, Actor) or hasattr(element, 'draw'): element.draw()
    for collectible in collectibles:
        if not collectible.collected: collectible.draw()
    for enemy in enemies:
        if not enemy.despawn_ready: enemy.draw()
    if knight:
        # Efeito de “piscar” quando invulnerável (não desenha em metade dos frames).
        if not knight.is_dashing and knight.invulnerable_timer > 0 and knight.invulnerable_timer % 8 < 4: pass
        else: knight.draw()
    # HUD de vida:
    for i in range(3):
        hearts[i].image = 'vida_do_jogador/0' if knight and i < knight.health else 'vida_do_jogador/2'
        hearts[i].draw()
    # HUD de score e contagem de inimigos vivos:
    if knight: screen.draw.text(f"Score: {knight.score}", topleft=(10, 50), fontsize=25, color="white")
    screen.draw.text(f"Enemies: {sum(1 for e in enemies if e.is_alive)}", topleft=(10, 80), fontsize=25, color="white")

def draw_game_over():
    # Sobrepõe um painel escuro translúcido e mostra mensagem de fim de jogo.
    draw_game(); screen.draw.filled_rect(Rect(0,0,WIDTH,HEIGHT), (0,0,0,200))
    screen.draw.text("GAME OVER", center=(WIDTH/2, HEIGHT/2-40), fontsize=80, color="red", shadow=(3,3))
    screen.draw.text("Pressione ENTER para voltar ao menu", center=(WIDTH/2, HEIGHT/2+40), fontsize=30, color="white")

def draw_victory():
    # Tela de vitória com score final e instrução de retorno ao menu.
    draw_game(); screen.draw.filled_rect(Rect(0,0,WIDTH,HEIGHT), (0,0,0,200))
    screen.draw.text("VICTORY!", center=(WIDTH/2, HEIGHT/2-60), fontsize=80, color="gold", shadow=(3,3))
    if knight: screen.draw.text(f"Final Score: {knight.score}", center=(WIDTH/2, HEIGHT/2+10), fontsize=40, color="white")
    screen.draw.text("Pressione ENTER para voltar ao menu", center=(WIDTH/2, HEIGHT/2+60), fontsize=30, color="white")

def draw_paused():
    # Tela de pausa com instruções para continuar ou voltar ao menu.
    draw_game(); screen.draw.filled_rect(Rect(0,0,WIDTH,HEIGHT), (0,0,0,180))
    screen.draw.text("PAUSADO", center=(WIDTH/2, HEIGHT/2-40), fontsize=80, color=GOLD, shadow=(3,3), owidth=2, ocolor=DARK_PURPLE)
    screen.draw.text("Pressione ESC para continuar", center=(WIDTH/2, HEIGHT/2+30), fontsize=30, color=WHITE)
    screen.draw.text("Pressione ENTER para voltar ao menu", center=(WIDTH/2, HEIGHT/2+70), fontsize=25, color=LIGHT_PURPLE)

# LOOP DE ATUALIZAÇÃO PRINCIPAL (UPDATE)
def update(dt):
    """Função principal de lógica, chamada a cada frame."""
    # Responsável por atualizar entidades e transitar entre estados (STARTING, PLAYING, GAME_OVER, VICTORY, PAUSED).
    global game_state, menu_screen, victory_timer, start_delay_timer
    if game_state == STARTING:
        # Permite uma “rampa” de entrada (fade-in) visual/sonora antes de habilitar o controle total.
        knight.update(platforms, traps, collectibles)
        for element in decorations + collectibles:
            if hasattr(element, 'update'): element.update()
        for enemy in enemies: enemy.update(knight, platforms)
        if start_delay_timer > 0:
            start_delay_timer -= 1
            progress = (MAX_START_DELAY - start_delay_timer) / MAX_START_DELAY
            music.set_volume(progress * 0.3)  # Aumenta volume gradualmente.
        else:
            game_state = PLAYING
    elif game_state == PLAYING and knight:
        # Atualização normal de gameplay: jogador, decorações animadas, colecionáveis e inimigos.
        knight.update(platforms, traps, collectibles)
        for element in decorations + collectibles:
            if hasattr(element, 'update'): element.update()
        for enemy in enemies[:]:
            enemy.update(knight, platforms)
            if enemy.despawn_ready: enemies.remove(enemy); continue
            # Resolução de danos (hitboxes de ataque do inimigo e do jogador):
            if enemy.is_alive and knight.is_alive:
                if enemy.get_attack_hitbox() and knight.actor.colliderect(enemy.get_attack_hitbox()): knight.take_damage()
                player_hitbox = knight.get_attack_hitbox()
                if player_hitbox and enemy.actor.colliderect(player_hitbox) and enemy not in knight.hit_enemies_this_attack:
                    enemy.take_damage(); knight.hit_enemies_this_attack.append(enemy); knight.hitstop_timer = 3
        # Transição para GAME_OVER após anim. de morte:
        if not knight.is_alive and knight.death_timer >= 15*knight.frame_speeds['default']: game_state = GAME_OVER
        # Lógica de vitória: quando não houver inimigos vivos, inicia um timer antes da tela de VICTORY.
        if victory_timer is None:
            if not any(e.is_alive for e in enemies) and knight.is_alive:
                victory_timer = 60
        else:
            victory_timer -= 1
            if victory_timer <= 0:
                game_state = VICTORY; stop_music(); play_music('victory', loops=0)
    elif game_state == PAUSED: pass  # Em pausa, não atualiza jogo (apenas desenha overlay/GUI).
    elif game_state in [GAME_OVER, VICTORY] and keyboard.RETURN:
        # ENTER na tela de fim leva ao menu principal e reinicia trilha.
        game_state, menu_screen = MENU, 'main'; stop_music(); play_music('menu_music')

# MANIPULADORES DE ENTRADA (INPUT)
def on_key_down(key):
    # Alterna pausa com ESC durante o jogo; no menu/pausa, ENTER retorna ao menu principal.
    global game_state
    if key == keys.ESCAPE:
        if game_state == PLAYING: game_state = PAUSED; play_sound('knight_jump', 1.0)  # Reuso de som curto para feedback.
        elif game_state == PAUSED: game_state = PLAYING; play_sound('knight_jump', 1.0)
    if game_state == PAUSED and key == keys.RETURN: game_state, menu_screen = MENU, 'main'; stop_music(); play_music('menu_music')
    if game_state == PLAYING and knight and knight.is_alive:
        # Interação com portas (E) quando sobrepostas.
        if key == keys.E:
            for door in doors:
                if knight.actor.colliderect(door.actor.inflate(10, 10)):
                    knight.actor.pos, knight.vy = door.destination, 0; play_sound('door_teleport'); break
        # Pulo: SPACE/UP/W; se não puder pular agora, aciona jump_buffer para “guardar” o comando por alguns frames.
        if key in [keys.SPACE, keys.UP, keys.W]:
            if knight.on_ground or knight.coyote_time > 0 or knight.jumps_left > 0: knight.jump()
            else: knight.jump_buffer = knight.jump_buffer_frames

def on_mouse_down(pos, button):
    # Clique esquerdo: atacar; clique direito: levantar escudo. No menu: clique em botões.
    global game_state, menu_screen, sound_enabled, music_enabled, start_delay_timer
    if game_state == MENU:
        if button == mouse.LEFT and menu_screen == 'main':
            if button_start.collidepoint(pos):
                play_sound('menu_click', 1.0); reset_game()
                game_state = STARTING; start_delay_timer = MAX_START_DELAY
                stop_music(); play_music('castle_theme'); music.set_volume(0)
            elif button_sound.collidepoint(pos):
                sound_enabled, music_enabled = not sound_enabled, not music_enabled; play_sound('menu_select', 1.0)
                if music_enabled: play_music('menu_music')
                else: stop_music()
            elif button_exit.collidepoint(pos): play_sound('menu_click', 1.0); exit()
    elif game_state == PLAYING and knight:
        if button == mouse.LEFT: knight.start_attack()
        elif button == mouse.RIGHT: knight.start_shield()

def on_mouse_up(pos, button):
    # Ao soltar o botão direito, baixa o escudo.
    if game_state == PLAYING and knight and button == mouse.RIGHT: knight.stop_shield()

def on_mouse_move(pos):
    # Atualiza posição do mouse para efeitos de hover nos botões do menu.
    global mouse_pos
    mouse_pos = pos

def reset_game():
    # Recria o nível, posiciona o cavaleiro e (re)cria o conjunto de inimigos com seus limites de patrulha.
    # Observação: lembre-se de ajustar limites de patrulha conforme o layout para evitar inimigos se prenderem em geometrias.
    global knight, enemies, victory_timer
    build_level(); knight = Knight(100, 500)
    enemies = [
        Skeleton(190, 410, 138, 340),  # Patrulha curta em plataforma baixa.
        Skeleton(640, 350, 490, 688),  # Patrulha na faixa central direita.
        Skeleton(700, 538, 554, 750),  # Piso inferior direito.
        Skeleton(680, 160, 586, 726)   # Plataforma superior.
    ]
    # Guarda o spawn original de cada inimigo (utilizado pelo “failsafe” de queda fora da tela).
    for enemy in enemies: enemy.original_spawn_pos = (enemy.actor.x, enemy.actor.y)
    victory_timer = None  # Limpa estado de vitória pendente.

# INÍCIO DO JOGO
play_music('menu_music')
pgzrun.go()
