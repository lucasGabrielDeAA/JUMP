#!/usr/bin/env python
# coding:utf-8

import cv2
import numpy as np
import sys
import json
import time
from optparse import OptionParser
from SimpleWebSocketServer import WebSocket, SimpleWebSocketServer
from multiprocessing import Process
import threading

processo = None

class Movimentos(object):

    '''
    Classe para simular uma enumeração com os possiveis valores para o movimento
    '''
    EM_PE = 0
    SUBINDO = 1
    DESCENDO = -1
    AGACHADO = -2


class GerenciadorEstadoJogador(object):

    '''
    Classe para gerenciar o estado do jogador
    '''
    # Constantes
    ARQUIVO_ESTADO_JOGADOR = './file/estado_jogador.json'
    ARQUIVO_ESTADO_VIDA_JOGADOR = './file/estado_jogo_cliente.json'

    class EstadosJogador(object):

        '''
        Classe para simular uma enumeração com os etados do jogador
        '''
        EM_PE = 0
        PULANDO = 1
        AGACHADO = -1

    def __init__(self, conexao=None):
        self.conexao = conexao
        self.atualizar_estado(Movimentos.EM_PE, False)
        self._set_vivo(True)

    def atualizar_estado(self, movimento, calibrado):
        '''
        Atualiza o estado do jogador no arquivo
        :param movimento: movimento do jogador
        :param calibrado: se a camera foi calibrada com o jogador
        '''
        novo_estado = 0
        if movimento == Movimentos.EM_PE:
            novo_estado = self.EstadosJogador.EM_PE
        elif movimento == Movimentos.SUBINDO:
            novo_estado = self.EstadosJogador.PULANDO
        elif movimento == Movimentos.AGACHADO:
            novo_estado = self.EstadosJogador.AGACHADO
        estado_jogador = {"movimento": novo_estado, "calibrado": calibrado}
        str_json = json.dumps(estado_jogador)
        if self.conexao is None:
            # Recria o arquivo e insere o novo estado do jogador
            print 'escreveu no arquivo: ', str_json
            with open(self.ARQUIVO_ESTADO_JOGADOR, 'w') as arq:
                arq.write(str_json)
        else:
            try:
                print self.conexao.address
                print 'Enviou: ', str_json
                self.conexao.sendMessage(str_json)
            except:
                print 'Não foi possível enviar a mensagem ao cliente'

    def _set_vivo(self, vivo):
        '''
        Seta o estado vivo do jogador
        :param vivo: se o jogador está vivo
        '''
        try:
            with open(self.ARQUIVO_ESTADO_VIDA_JOGADOR, 'r') as arq:
                estado_jogo = json.loads(arq.read())
                estado_jogo['jogador_vivo'] = vivo
            with open(self.ARQUIVO_ESTADO_VIDA_JOGADOR, 'w') as arq:
                arq.write(json.dumps(estado_jogo))
        except ValueError as e:
            print e

    def is_vivo(self):
        '''
        verifica se o jogador está vivo ou não
        :returns: True se o jogador está vivo e False se não
        '''
        try:
            with open(self.ARQUIVO_ESTADO_VIDA_JOGADOR) as arq:
                vivo_str = arq.read()
                print vivo_str
            vivo = json.loads(vivo_str)
            return vivo['jogador_vivo']
        except ValueError as e:
            print e
            return False

    def tela_atual(self):
        '''
        retorna a tela atual do jogo
        :returns: a tela atual do jogo
        '''
        with open(self.ARQUIVO_ESTADO_VIDA_JOGADOR) as arq:
            str_estado_jogo = arq.read()
        estado_jogo = json.loads(str_estado_jogo)
        tela = estado_jogo['tela']
        return tela

    def finish(self):
        '''
        finaliza o estado do gerenciador
        '''
        self.atualizar_estado(Movimentos.EM_PE, False)
        self._set_vivo(True)


class DetectorMovimento(threading.Thread):

    '''
    Classe para detectar o movimento
    '''
    # Constantes
    ALTURA_QUADRADO_CENTRO = 80
    LARGURA_QUADRADO_CENTRO = 200
    MARGEM_ERRO_CALIBRACAO = 20
    # evita que um simples aumento na altura da pessoa seja considerado um pulo
    MARGEM_TOLERANCIA = 70
    NUM_Y_ANALIZADOS = 5

    NUM_Y_GUARDADOS = 5

    ALTURA_AGACHAMENTO = 340

    class VariacoesMovimento(object):

        '''
        Classe para simular uma enumeração com as variações de movimento
        '''
        PARA_CIMA = 1
        PARA_BAIXO = -1
        SEM_MOVIMENTO = 0

    def __init__(self, id_camera=0, agachar_desabilitado=False, conexao=None):
        '''
        Construtor da Classe
        :param id_camera: identificador da camera que será utilizada, o padrão é 0
        '''
        threading.Thread.__init__(self)
        self.conexao = conexao
        self.movimento = Movimentos.EM_PE
        self.id_camera = id_camera
        self.agachar_desabilitado = agachar_desabilitado

        if conexao is None:
            self.camera = cv2.VideoCapture(self.id_camera)
        else:
            self.camera = conexao.camera
        if not self.camera.isOpened():
            raise IOError('Não foi possivel ter acesso a camera')
        if self.NUM_Y_ANALIZADOS > self.NUM_Y_GUARDADOS:
            raise ValueError(
                "Número de Y analisados deve ser igual ou menor que o número de Y guardados")
        self.width, self.height = self.camera.get(3), self.camera.get(4)
        print 'Resolução da camera {0} x {1}'.format(self.width, self.height)

        self.ys = []
        self.desenhar_linhas = False
        self.calibrado = False

        self.gerenciador_estado_jogador = GerenciadorEstadoJogador(
            conexao=self.conexao)

    def return_name(self):
        '''
        Retorna o nome do processo
        :returns: nome do processo
        '''
        return 'Processo de detecção de movimentos'

    def run(self):
        '''
        Inicia a detecção
        '''
        return self.iniciar()

    def get_thresholded_image(self, hsv):
        '''
        Gera uma faixa de cor
        :param hsv: imagem no formato de cor hsv
        :returns: a faixa de cor
        '''
        min_cor = np.array((110, 100, 80), np.uint8)
        max_cor = np.array((140, 190, 190), np.uint8)

        faixa_cor = cv2.inRange(hsv, min_cor, max_cor)
        return faixa_cor

    def verificar_movimento(self):
        '''
        Verifica se houve movimento e se foi para baixo ou para cima
        :returns: 0 se não houve movimento, 1 se houve movimento para cima e -1 se houve movimento para baixo
        '''
        ultimos_valores_y = [0]
        if len(self.ys) >= self.NUM_Y_ANALIZADOS:
            ultimos_valores_y = self.ys[
                len(self.ys) - self.NUM_Y_ANALIZADOS:len(self.ys)]
        # houve diferenca maior que a margem entre dois pontos Y dentro do
        # numero de pontos analizados
        if max(ultimos_valores_y) - min(ultimos_valores_y) > self.MARGEM_TOLERANCIA:
            ultimo_y = self.ys[len(self.ys) - 1]
            primeiro_y = self.ys[0]
            if primeiro_y < ultimo_y:  # ta descendo
                return self.VariacoesMovimento.PARA_BAIXO
            else:  # ta subindo
                return self.VariacoesMovimento.PARA_CIMA
        else:
            return self.VariacoesMovimento.SEM_MOVIMENTO

    def iniciar(self):
        '''
        Inicia a detecção
        '''
        # so inica a deteccao caso o jogo esteja no menu
        while self.gerenciador_estado_jogador.tela_atual() != 'menu':
            print 'Jogo não está na tela de menu'
            time.sleep(0.5)

        momento_pulo = {}
        momento_agachar = {}
        centro_x, centro_y = (int)(self.width / 2), (int)(self.height / 2)

        # print 'Numero de frames:
        # {0}'.format(self.camera.get(cv2.cv.CV_CAP_PROP_FRAME_COUNT))
        contador = 0
        while(self.camera.isOpened()):
            contador = contador + 1
            # a cada N loops ele verifica se o jogador ta vivo
            if contador % 50 == 0:
                if not self.gerenciador_estado_jogador.is_vivo():
                    print 'Jogador perdeu'
                    break
            _, frame = self.camera.read()
            frame = cv2.flip(frame, 1)
            blur = cv2.medianBlur(frame, 5)
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

            faixa_cor = self.get_thresholded_image(hsv)
            erode = cv2.erode(faixa_cor, None, iterations=3)
            dilate = cv2.dilate(erode, None, iterations=10)

            contours, hierarchy = cv2.findContours(
                dilate, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

            # desenha o quadrado no centro, para calibrar
            cv2.rectangle(
                frame, (centro_x - (self.LARGURA_QUADRADO_CENTRO / 2),
                        centro_y - (self.ALTURA_QUADRADO_CENTRO / 2)),
                (centro_x + (self.LARGURA_QUADRADO_CENTRO / 2), centro_y + (self.ALTURA_QUADRADO_CENTRO / 2)), [0, 255, 0], 2)

            if not self.calibrado:
                self.ys = []
                momento_pulo['y'] = None
                momento_agachar['y'] = None

            if contours:
                maior_area = 0
                maior_contorno = contours[0]
                for cont in contours:
                    cx, cy, cw, ch = cv2.boundingRect(cont)
                    area = cw * ch
                    if area > maior_area:
                        maior_area = area
                        maior_contorno = cont

                x, y, w, h = cv2.boundingRect(maior_contorno)
                cx, cy = x + w / 2, y + h / 2

                # verifica se ta no centro
                if y > centro_y - (self.ALTURA_QUADRADO_CENTRO / 2) - self.MARGEM_ERRO_CALIBRACAO and \
                    y < centro_y - (self.ALTURA_QUADRADO_CENTRO / 2) + self.MARGEM_ERRO_CALIBRACAO and \
                    y + h > centro_y + (self.ALTURA_QUADRADO_CENTRO / 2) - self.MARGEM_ERRO_CALIBRACAO and \
                        y + h < centro_y + (self.ALTURA_QUADRADO_CENTRO / 2) + self.MARGEM_ERRO_CALIBRACAO:
                    if not self.calibrado:
                        print 'Calibrou'
                        self.calibrado = True
                        self.gerenciador_estado_jogador.atualizar_estado(
                            self.movimento, self.calibrado)
                    # dentro do quadrado
                    cv2.rectangle(
                        frame, (centro_x - (self.LARGURA_QUADRADO_CENTRO / 2),
                                centro_y - (self.ALTURA_QUADRADO_CENTRO / 2)),
                        (centro_x + (self.LARGURA_QUADRADO_CENTRO / 2), centro_y + (self.ALTURA_QUADRADO_CENTRO / 2)), [0, 0, 255], 2)

                # print hsv.item(cy, cx, 0), hsv.item(cy, cx, 1), hsv.item(cy, cx, 2)
                # if 100 < hsv.item(cy, cx, 0) < 120:
                cv2.rectangle(frame, (x, y), (x + w, y + h), [255, 0, 0], 2)

                if len(self.ys) >= self.NUM_Y_GUARDADOS:
                    self.ys = self.ys[1:self.NUM_Y_GUARDADOS]
                self.ys.append(y)
                # ta guardando ate NUM_Y_GUARDADOS Y
                if self.calibrado:
                    # verifica o tipo do movimento, 1 para subiu e -1 para
                    # desceu e 0 para nao movimentou
                    variacao_movimento = self.verificar_movimento()
                    mudou_movimento = False
                    if variacao_movimento:
                        # guarda o movimento antigo, mas pra nada
                        movimento_antigo = self.movimento
                        # subiu, mas o que houve?
                        if variacao_movimento == self.VariacoesMovimento.PARA_CIMA:
                            # pulou
                            if self.movimento == Movimentos.EM_PE:
                                self.movimento = Movimentos.SUBINDO
                                momento_pulo['y'] = y
                                mudou_movimento = True
                            # levantou
                            elif self.movimento == Movimentos.AGACHADO:
                                # and y > momento_agachar['y'] -
                                # self.MARGEM_TOLERANCIA
                                if momento_agachar['y'] != None and y < momento_agachar['y'] + self.MARGEM_TOLERANCIA:
                                    self.movimento = Movimentos.EM_PE
                                    mudou_movimento = True
                        # desceu, mas o que houve?
                        elif variacao_movimento == self.VariacoesMovimento.PARA_BAIXO:
                            # agachou
                            if self.movimento == Movimentos.EM_PE and not self.agachar_desabilitado and y > self.ALTURA_AGACHAMENTO:
                                momento_agachar['y'] = y
                                self.movimento = Movimentos.AGACHADO
                                mudou_movimento = True
                            # ta descendo do pulo
                            elif self.movimento == Movimentos.SUBINDO:
                                self.movimento = Movimentos.DESCENDO
                                mudou_movimento = True

                        if self.movimento == Movimentos.DESCENDO:
                            # voltou ao chao
                            # and y < momento_pulo['y'] +
                            # self.MARGEM_TOLERANCIA:
                            if momento_pulo['y'] != None and y > momento_pulo['y'] - self.MARGEM_TOLERANCIA:
                                self.movimento = Movimentos.EM_PE
                                momento_pulo['y'] = None
                                mudou_movimento = True
                        # print 'mov:{0} mov_ant: {1} mov_var:
                        # {2}'.format(self.movimento, movimento_antigo,
                        # variacao_movimento)
                        if mudou_movimento:
                            if self.movimento == Movimentos.SUBINDO:
                                print 'Pulou em px: {0}'.format(momento_pulo['y'])
                            elif self.movimento == Movimentos.AGACHADO:
                                print 'Agachou em px: {0}'.format(momento_agachar['y'])
                            elif self.movimento == Movimentos.EM_PE:
                                print 'De pé em px: {0}'.format(y)
                            self.gerenciador_estado_jogador.atualizar_estado(
                                self.movimento, self.calibrado)
                            # print self.ys
                    # nao houve variacao grande entre os pontos
                    else:
                        # and y < momento_pulo['y'] + self.MARGEM_TOLERANCIA:
                        if momento_pulo['y'] != None and y > momento_pulo['y'] - self.MARGEM_TOLERANCIA:
                            if self.movimento == Movimentos.DESCENDO:
                                print 'De pé em px: {0}'.format(y)
                                self.movimento = Movimentos.EM_PE
                                momento_pulo['y'] = None
                                self.gerenciador_estado_jogador.atualizar_estado(
                                    self.movimento, self.calibrado)
                                mudou_movimento = True
                        # and y > momento_agachar['y'] - self.MARGEM_TOLERANCIA:
                        # não considera a margem de tolerancia, pois ao agachar
                        # ele pode ja levantar. O ideal seria uma outra margem,
                        # mas menor
                        if momento_agachar['y'] != None and y < momento_agachar['y'] - self.MARGEM_TOLERANCIA:
                            if self.movimento == Movimentos.AGACHADO:
                                print 'De pé em px: {0}'.format(y)
                                self.movimento = Movimentos.EM_PE
                                momento_agachar['y'] = None
                                self.gerenciador_estado_jogador.atualizar_estado(
                                    self.movimento, self.calibrado)
                                mudou_movimento = True
                    if self.movimento == Movimentos.EM_PE and mudou_movimento:
                        # if momento_agachar['y']:
                        #    for i in self.ys:
                        #        if i < momento_agachar['y']:
                        #            self.ys.remove(i)
                        # else:
                        self.ys = []

            if self.desenhar_linhas:
                # linha superior (640 x 50)
                cv2.line(frame, (0, 50), (int(self.width), 50),
                         (0, 255, 255), 2)

                # linha inferior (640 x 430)
                cv2.line(frame, (0, int(self.height - 50)),
                         (int(self.width), int(self.height - 50)), (0, 255, 255), 2)

                # linha que define se o usuário agachou (640 x 330)
                cv2.line(frame, (0, int(self.height - 150)),
                         (int(self.width), int(self.height - 150)), (0, 0, 255), 2)

            cv2.imshow('JUMP! Detecção', frame)

            key = cv2.waitKey(25)
            if key == 27:  # esc
                break
        self.reiniciar()
        '''if self.conexao is None:
            self.reiniciar()
        else:
            self.finalizar()'''

    def reiniciar(self):
        '''
        reinicia a detecção e os recursos
        '''
        print 'reiniciando captura...'
        self.ys = []
        self.desenhar_linhas = False
        self.calibrado = False
        self.gerenciador_estado_jogador.finish()
        if self.conexao is None:
            self.gerenciador_estado_jogador = GerenciadorEstadoJogador()
        else:
            self.gerenciador_estado_jogador = GerenciadorEstadoJogador(conexao=self.conexao)
        self.iniciar()

    def finalizar(self):
        '''
        finaliza a detecção e os recursos
        '''
        self.calibrado = False
        self.movimento = Movimentos.EM_PE
        self.gerenciador_estado_jogador.finish()
        self.camera.release()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    parser = OptionParser()
    parser.add_option("-c", "--camera", dest="id_camera",
                      help="id da camera", type="int", default=0)
    parser.add_option("-a", "--desagachar", dest="agachar_desabilitado",
                      action="store_true", help="Desabilitar agachar", default=False)
    parser.add_option(
        "-q", "--quiet", action="store_false", dest="verbose", default=True)
    (options, args) = parser.parse_args()

    detector_movimento = DetectorMovimento(
        options.id_camera, options.agachar_desabilitado)
    detector_movimento.iniciar()
    detector_movimento.finalizar()
