import tkinter as tk
from tkinter import ttk
import customtkinter as ctk
import re

METADADOS = {
    "categoria": ["idcategoria", "descricao"],
    "produto": ["idproduto", "nome", "descricao", "preco", "quantestoque", "categoria_idcategoria"],
    "tipocliente": ["idtipocliente", "descricao"],
    "cliente": ["idcliente", "nome", "email", "nascimento", "senha", "tipocliente_idtipocliente", "dataregistro"],
    "tipoendereco": ["idtipoendereco", "descricao"],
    "endereco": ["idendereco", "enderecopadrao", "logradouro", "numero", "complemento", "bairro", "cidade", "uf", "cep", "tipoendereco_idtipoendereco", "cliente_idcliente"],
    "telefone": ["numero", "cliente_idcliente"],
    "status": ["idstatus", "descricao"],
    "pedido": ["idpedido", "status_idstatus", "datapedido", "valortotalpedido", "cliente_idcliente"],
    "pedido_has_produto": ["idpedidoproduto", "pedido_idpedido", "produto_idproduto", "quantidade", "precounitario"]
}

OPERADORES_VALIDOS = ['=', '>', '<', '<=', '>=', '<>', 'and', '(', ')']

class NoArvore:
    def __init__(self, rotulo, esquerda=None, direita=None):
        self.rotulo = rotulo
        self.esquerda = esquerda
        self.direita = direita

def construir_arvore_padrao(colunas, tabela_principal, joins, condicao_where):
    raiz_atual = NoArvore(f"Ler Tabela: {tabela_principal}")
    for j in joins:
        raiz_atual = NoArvore(f"⋈ Junção: {j['condicao']}", esquerda=raiz_atual, direita=NoArvore(f"Ler Tabela: {j['tabela']}"))
    if condicao_where:
        raiz_atual = NoArvore(f"σ Filtro: {condicao_where}", esquerda=raiz_atual)
    cols = ", ".join(colunas)
    if len(cols) > 30: cols = cols[:27] + "..."
    return NoArvore(f"π Projeção: {cols}", esquerda=raiz_atual)

def construir_arvore_otimizada(colunas, tabela_principal, joins, condicao_where):
    tabelas_ativas = [tabela_principal] + [j['tabela'] for j in joins]
    condicoes_por_tabela = {tab: [] for tab in tabelas_ativas}
    condicoes_globais = []
    
    if condicao_where:
        partes_where = [p.strip() for p in condicao_where.split(' and ')]
        for parte in partes_where:
            tabs_envolvidas = [t for t in tabelas_ativas if re.search(rf'\b{t}\.', parte)]
            if len(tabs_envolvidas) == 1:
                condicoes_por_tabela[tabs_envolvidas[0]].append(parte)
            else:
                condicoes_globais.append(parte)

    nos_tabelas = {}
    for tab in tabelas_ativas:
        no = NoArvore(f"Ler Tabela: {tab}")
        if condicoes_por_tabela[tab]:
            conds_str = " AND ".join(condicoes_por_tabela[tab])
            no = NoArvore(f"σ Filtrar: {conds_str}", esquerda=no)
        no = NoArvore(f"π Reduzir Atributos: {tab}", esquerda=no)
        nos_tabelas[tab] = no

    raiz_atual = nos_tabelas[tabela_principal]
    for j in joins:
        raiz_atual = NoArvore(f"⋈ Fazer Junção: {j['condicao']}", esquerda=raiz_atual, direita=nos_tabelas[j['tabela']])
        
    if condicoes_globais:
         conds_str = " AND ".join(condicoes_globais)
         raiz_atual = NoArvore(f"σ Filtro Final: {conds_str}", esquerda=raiz_atual)
         
    cols = ", ".join(colunas)
    if len(cols) > 30: cols = cols[:27] + "..."
    return NoArvore(f"π Projeção Final: {cols}", esquerda=raiz_atual)

def gerar_plano_execucao(no, plano=None):
    if plano is None: plano = []
    if not no: return plano
    gerar_plano_execucao(no.esquerda, plano)
    gerar_plano_execucao(no.direita, plano)
    plano.append(no.rotulo)
    return plano

def gerar_algebra_relacional(colunas, tabela_principal, joins, condicao_where):
    lista_colunas = ", ".join(colunas)
    corpo_relacoes = tabela_principal
    for j in joins:
        corpo_relacoes = f"({corpo_relacoes} ⋈_{{{j['condicao']}}} {j['tabela']})"
    if condicao_where:
        return f"π_{{{lista_colunas}}} ( σ_{{{condicao_where}}} ( {corpo_relacoes} ) )"
    return f"π_{{{lista_colunas}}} ( {corpo_relacoes} )"

def normalizar_consulta(query):
    query = query.lower().strip()
    query = query.replace(';', '')  
    query = re.sub(r'(<=|>=|<>|<|>|=)', r' \1 ', query)
    query = query.replace('(', ' ( ').replace(')', ' ) ')
    return re.sub(r'\s+', ' ', query).strip()

def validar_atributo(tabelas_ativas, atributo_raw):
    atributo = atributo_raw.strip()
    if atributo == '*' or (atributo.startswith("'") and atributo.endswith("'")): 
        return True, ""
    if re.match(r'^-?\d+(\.\d+)?$', atributo): 
        return True, ""
        
    if '.' in atributo:
        tabela, coluna = atributo.split('.', 1)
        if tabela not in tabelas_ativas: return False, f"Tabela '{tabela}' não referenciada."
        if coluna not in METADADOS[tabela] and coluna != '*': return False, f"Atributo '{coluna}' não existe."
        return True, ""
    tabelas_enc = [tab for tab in tabelas_ativas if atributo in METADADOS[tab]]
    if len(tabelas_enc) == 0: return False, f"Atributo '{atributo}' não encontrado."
    if len(tabelas_enc) > 1: return False, f"Atributo ambíguo: '{atributo}'."
    return True, ""

def parse_e_validar(query_original):
    if not query_original.strip(): return False, "Consulta vazia.", None, None, ""
    query = normalizar_consulta(query_original)
    if not query.startswith("select ") or " from " not in query: return False, "Sintaxe básica inválida.", None, None, ""

    tabelas_ativas, lista_joins, string_where = [], [], ""
    
    try:
        match_select = re.search(r'select\s+(.*?)\s+from\s+', query)
        if not match_select: return False, "Malformação SELECT/FROM.", None, None, ""
        
        bloco_select, match_select_end = match_select.group(1), match_select.end()
        resto_query = query[match_select_end:]
        tabela_principal = resto_query.split(' ', 1)[0]
        
        if tabela_principal not in METADADOS: return False, f"A tabela '{tabela_principal}' não existe.", None, None, ""
        tabelas_ativas.append(tabela_principal)
        resto_query = resto_query.split(' ', 1)[1] if len(resto_query.split(' ', 1)) > 1 else ""
        
        while resto_query.startswith("join "):
            resto_query = resto_query[5:].strip()
            tabela_join = re.match(r'^(\w+)', resto_query).group(1)
            if tabela_join not in METADADOS: return False, f"Tabela '{tabela_join}' inexistente.", None, None, ""
            tabelas_ativas.append(tabela_join)
            resto_query = resto_query[len(tabela_join):].strip()
            
            if not resto_query.startswith("on "): return False, "Faltando cláusula ON.", None, None, ""
            resto_query = resto_query[3:].strip()
            
            condicao_on = re.search(r'^(.*?)(?=\s+join\s+|\s+where\s+|$)', resto_query).group(1).strip()
            lista_joins.append({'tabela': tabela_join, 'condicao': condicao_on})
            
            for token in condicao_on.split():
                if token not in OPERADORES_VALIDOS and not re.match(r'^-?\d+(\.\d+)?$', token):
                     valido, msg = validar_atributo(tabelas_ativas, token)
                     if not valido: return False, msg, None, None, ""
            resto_query = resto_query[len(condicao_on):].strip()

        if resto_query.startswith("where "):
            string_where = resto_query[6:].strip()
            for token in string_where.split():
                 if token not in OPERADORES_VALIDOS and not re.match(r'^-?\d+(\.\d+)?$', token):
                     token_limpo = token.replace('(', '').replace(')', '')
                     if token_limpo:
                         valido, msg = validar_atributo(tabelas_ativas, token_limpo)
                         if not valido: return False, msg, None, None, ""

        colunas = [c.strip() for c in bloco_select.split(',')]
        for col in colunas:
            valido, msg = validar_atributo(tabelas_ativas, col)
            if not valido: return False, msg, None, None, ""

        algebra = gerar_algebra_relacional(colunas, tabela_principal, lista_joins, string_where)
        arvore_p = construir_arvore_padrao(colunas, tabela_principal, lista_joins, string_where)
        arvore_o = construir_arvore_otimizada(colunas, tabela_principal, lista_joins, string_where)

        return True, "Consulta Válida e Processada com Sucesso!", arvore_p, arvore_o, algebra
    except Exception as e:
        return False, f"Erro interno de processamento: {str(e)}", None, None, ""


class SGBDModernApp:
    def __init__(self, root):
        self.root = root
        self.root.title("SGBD Didático - Analisador e Otimizador")
        self.root.geometry("1100x750")
        
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")
        
        self.arvore_padrao = None
        self.arvore_otimizada = None
        self.modo_grafo = tk.StringVar(value="Otimizado")

        self.drag_data = {"x": 0, "y": 0, "item": None}
        self.node_counter = 0

        self.construir_interface()
        self.estilizar_treeview() 

    def estilizar_treeview(self):
        style = ttk.Style()
        style.theme_use("default")
        style.configure("Treeview", 
                        background="#2b2b2b", foreground="white", rowheight=30, 
                        fieldbackground="#2b2b2b", bordercolor="#343638", borderwidth=0)
        style.map('Treeview', background=[('selected', '#1f538d')])
        style.configure("Treeview.Heading", 
                        background="#565b5e", foreground="white", relief="flat", font=("Segoe UI", 11, "bold"))
        style.map("Treeview.Heading", background=[('active', '#343638')])

    def construir_interface(self):
        self.header = ctk.CTkFrame(self.root, corner_radius=0, fg_color="transparent")
        self.header.pack(fill="x", padx=20, pady=(15, 0))
        ctk.CTkLabel(self.header, text="Processador de Consultas SQL", 
                     font=ctk.CTkFont(family="Segoe UI", size=24, weight="bold")).pack(side="left")

        self.tabview = ctk.CTkTabview(self.root, corner_radius=10)
        self.tabview.pack(fill="both", expand=True, padx=20, pady=(10, 20))

        self.tab_editor = self.tabview.add("1. Editor SQL")
        self.tab_grafo = self.tabview.add("2. Grafo de Execução")
        self.tab_plano = self.tabview.add("3. Plano de Execução")

        self.construir_aba_editor()
        self.construir_aba_grafo()
        self.construir_aba_plano()

    def construir_aba_editor(self):
        ctk.CTkLabel(self.tab_editor, text="Digite sua consulta SQL:", 
                     font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold")).pack(anchor="w", pady=(10, 5), padx=10)
        
        self.text_sql = ctk.CTkTextbox(self.tab_editor, height=180, font=("Consolas", 14), 
                                       border_width=2, border_color="#3b3b3b", corner_radius=8)
        self.text_sql.pack(fill="x", padx=10, pady=(0, 15))
        self.text_sql.insert("0.0", "Select cliente.nome, pedido.idPedido, pedido.DataPedido, Status.descricao, pedido.ValorTotalPedido\nfrom Cliente Join pedido on cliente.idcliente = pedido.Cliente_idCliente\nJoin Status on Status.idstatus = Pedido.status_idstatus\nwhere Status.descricao = 'Aberto' and cliente.TipoCliente_idTipoCliente = 1 and pedido.ValorTotalPedido = 0;")

        frame_controles = ctk.CTkFrame(self.tab_editor, fg_color="transparent")
        frame_controles.pack(fill="x", padx=10)
        
        btn_executar = ctk.CTkButton(frame_controles, text="▶ Executar Consulta", 
                                     font=ctk.CTkFont(weight="bold"), 
                                     command=self.processar_consulta, height=40)
        btn_executar.pack(side="left", pady=5)
        
        self.lbl_status = ctk.CTkLabel(frame_controles, text="Aguardando execução", 
                                       text_color="gray", font=ctk.CTkFont(size=14))
        self.lbl_status.pack(side="left", padx=20)

        ctk.CTkLabel(self.tab_editor, text="Expressão em Álgebra Relacional:", 
                     font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold")).pack(anchor="w", pady=(25, 5), padx=10)
                     
        self.text_algebra = ctk.CTkTextbox(self.tab_editor, height=80, font=("Cambria Math", 16), 
                                           border_width=1, fg_color="#1a1a1a", text_color="#a5d6ff")
        self.text_algebra.pack(fill="x", padx=10)
        self.text_algebra.configure(state="disabled")

    def construir_aba_grafo(self):
        frame_toggle = ctk.CTkFrame(self.tab_grafo, fg_color="transparent")
        frame_toggle.pack(fill="x", pady=(10, 10), padx=10)
        
        ctk.CTkLabel(frame_toggle, text="Estratégia:", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=(0,15))
        
        ctk.CTkRadioButton(frame_toggle, text="Padrão (Sem otimização)", variable=self.modo_grafo, 
                           value="Padrao", command=self.desenhar_grafo).pack(side="left", padx=10)
        ctk.CTkRadioButton(frame_toggle, text="Otimizado (Heurísticas)", variable=self.modo_grafo, 
                           value="Otimizado", command=self.desenhar_grafo).pack(side="left", padx=10)

        frame_canvas = ctk.CTkFrame(self.tab_grafo, corner_radius=10, border_width=2, border_color="#3b3b3b")
        frame_canvas.pack(fill="both", expand=True, padx=10, pady=10)
        
        self.canvas = tk.Canvas(frame_canvas, bg="#202124", bd=0, highlightthickness=0)
        
        scroll_y = ctk.CTkScrollbar(frame_canvas, orientation="vertical", command=self.canvas.yview)
        scroll_x = ctk.CTkScrollbar(frame_canvas, orientation="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        
        self.canvas.grid(row=0, column=0, sticky="nsew", padx=(5,0), pady=(5,0))
        scroll_y.grid(row=0, column=1, sticky="ns", pady=5, padx=2)
        scroll_x.grid(row=1, column=0, sticky="ew", padx=5, pady=2)
        
        frame_canvas.grid_rowconfigure(0, weight=1)
        frame_canvas.grid_columnconfigure(0, weight=1)

        self.canvas.tag_bind("movable", "<ButtonPress-1>", self.on_drag_start)
        self.canvas.tag_bind("movable", "<B1-Motion>", self.on_drag_motion)
        self.canvas.tag_bind("movable", "<Enter>", lambda e: self.canvas.configure(cursor="hand2"))
        self.canvas.tag_bind("movable", "<Leave>", lambda e: self.canvas.configure(cursor=""))

    def on_drag_start(self, event):
        cx, cy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        item = self.canvas.find_withtag("current")[0]
        tags = self.canvas.gettags(item)
        
        node_id = next((t for t in tags if t.startswith("node_")), None)
        if node_id:
            self.drag_data["item"] = node_id
            self.drag_data["x"] = cx
            self.drag_data["y"] = cy

    def on_drag_motion(self, event):
        cx, cy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        node_id = self.drag_data["item"]
        if not node_id: return

        delta_x = cx - self.drag_data["x"]
        delta_y = cy - self.drag_data["y"]

        self.canvas.move(node_id, delta_x, delta_y)

        for line_id in self.canvas.find_withtag(f"from_{node_id}"):
            coords = self.canvas.coords(line_id)
            self.canvas.coords(line_id, coords[0] + delta_x, coords[1] + delta_y, coords[2], coords[3])

        for line_id in self.canvas.find_withtag(f"to_{node_id}"):
            coords = self.canvas.coords(line_id)
            self.canvas.coords(line_id, coords[0], coords[1], coords[2] + delta_x, coords[3] + delta_y)

        self.drag_data["x"] = cx
        self.drag_data["y"] = cy

    def construir_aba_plano(self):
        ctk.CTkLabel(self.tab_plano, text="Plano de Execução (Post-order Traversal):", 
                     font=ctk.CTkFont(weight="bold", size=14)).pack(anchor="w", pady=(10, 10), padx=10)
        
        frame_tree = ctk.CTkFrame(self.tab_plano)
        frame_tree.pack(fill="both", expand=True, padx=10, pady=(0,10))

        colunas = ("passo", "operador", "detalhe")
        self.tree = ttk.Treeview(frame_tree, columns=colunas, show="headings", height=15)
        
        self.tree.heading("passo", text="Nº")
        self.tree.heading("operador", text="Operação")
        self.tree.heading("detalhe", text="Detalhes do Nó")
        
        self.tree.column("passo", width=50, anchor="center")
        self.tree.column("operador", width=150, anchor="w")
        self.tree.column("detalhe", width=600, anchor="w")
        
        # Tags de cores adaptadas para Dark Mode (fundo sutil, texto claro)
        self.tree.tag_configure('ler', background='#172c1c', foreground='#a1e0b5')
        self.tree.tag_configure('filtro', background='#331d1d', foreground='#f0a1a1')
        self.tree.tag_configure('juncao', background='#332b16', foreground='#e6cd91')
        self.tree.tag_configure('projecao', background='#1c2a38', foreground='#9ac5f5')
        
        scrollbar = ctk.CTkScrollbar(frame_tree, orientation="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def processar_consulta(self):
        consulta = self.text_sql.get("0.0", tk.END)
        sucesso, msg, arvore_p, arvore_o, algebra = parse_e_validar(consulta)
        
        self.text_algebra.configure(state="normal")
        self.text_algebra.delete("0.0", tk.END)
        self.canvas.delete("all")
        for item in self.tree.get_children(): self.tree.delete(item)
        
        if sucesso:
            self.lbl_status.configure(text=f"✅ {msg}", text_color="#2ea043")
            self.text_algebra.insert("0.0", algebra)
            self.arvore_padrao = arvore_p
            self.arvore_otimizada = arvore_o
            
            self.desenhar_grafo()
            self.preencher_plano_execucao()
            
            self.tabview.set("2. Grafo de Execução")
        else:
            self.lbl_status.configure(text=f"❌ {msg}", text_color="#f85149")
            self.tabview.set("1. Editor SQL")
            
        self.text_algebra.configure(state="disabled")

    def desenhar_grafo(self):
        self.canvas.update_idletasks()
        self.canvas.delete("all")
        self.node_counter = 0
        
        largura_canvas = self.canvas.winfo_width()
        if largura_canvas <= 1: largura_canvas = 1000
        
        arvore = self.arvore_padrao if self.modo_grafo.get() == "Padrao" else self.arvore_otimizada
        if arvore:
            self._desenhar_no_recursivo(arvore, x=largura_canvas/2, y=50, dx=350, dy=90)
            
            bbox = self.canvas.bbox("all")
            if bbox:
                min_x, min_y, max_x, max_y = bbox
                largura_desenho = max_x - min_x
                
                centro_desenho = min_x + (largura_desenho / 2)
                centro_canvas = largura_canvas / 2
                offset_x = centro_canvas - centro_desenho
                
                if largura_desenho > largura_canvas: 
                    offset_x = 50 - min_x
                
                offset_y = 50 - min_y
                    
                self.canvas.move("all", offset_x, offset_y)
                
                novo_bbox = self.canvas.bbox("all")
                if novo_bbox:
                    self.canvas.configure(scrollregion=(novo_bbox[0]-50, novo_bbox[1]-50, novo_bbox[2]+50, novo_bbox[3]+50))

    def _desenhar_no_recursivo(self, no, x, y, dx, dy):
        if not no: return None
        
        self.node_counter += 1
        current_node_id = f"node_{self.node_counter}"

        if no.esquerda and no.direita:
            child_x_esq, child_y_esq = x - dx, y + dy
            child_x_dir, child_y_dir = x + dx, y + dy
            
            line_id_esq = self.canvas.create_line(x, y, child_x_esq, child_y_esq, arrow=tk.LAST, fill="#6e7681", width=2, tags=(f"from_{current_node_id}",))
            line_id_dir = self.canvas.create_line(x, y, child_x_dir, child_y_dir, arrow=tk.LAST, fill="#6e7681", width=2, tags=(f"from_{current_node_id}",))
            
            novo_dx = max(dx * 0.6, 140)
            
            child_node_id_esq = self._desenhar_no_recursivo(no.esquerda, child_x_esq, child_y_esq, novo_dx, dy)
            child_node_id_dir = self._desenhar_no_recursivo(no.direita, child_x_dir, child_y_dir, novo_dx, dy)
            
            self.canvas.addtag_withtag(f"to_{child_node_id_esq}", line_id_esq)
            self.canvas.addtag_withtag(f"to_{child_node_id_dir}", line_id_dir)
            
        elif no.esquerda:
            child_x, child_y = x, y + dy
            line_id = self.canvas.create_line(x, y, child_x, child_y, arrow=tk.LAST, fill="#6e7681", width=2, tags=(f"from_{current_node_id}",))
            
            child_node_id = self._desenhar_no_recursivo(no.esquerda, child_x, child_y, dx, dy)
            self.canvas.addtag_withtag(f"to_{child_node_id}", line_id)

        partes = no.rotulo.split(":", 1)
        operacao = partes[0].strip()
        
        if "π" in operacao or "Reduzir" in operacao:
            cor_bg, cor_borda = "#1f3a5c", "#58a6ff" 
        elif "⋈" in operacao:
            cor_bg, cor_borda = "#5c4b1e", "#e3b341" 
        elif "σ" in operacao:
            cor_bg, cor_borda = "#5c1e1e", "#f85149" 
        else:
            cor_bg, cor_borda = "#1e4620", "#2ea043" 

        texto_exibicao = no.rotulo
        if len(texto_exibicao) > 40:
            meio = len(texto_exibicao) // 2
            espaco = texto_exibicao.find(" ", meio)
            if espaco == -1: espaco = texto_exibicao.rfind(" ", 0, meio)
            if espaco != -1:
                texto_exibicao = texto_exibicao[:espaco] + "\n" + texto_exibicao[espaco+1:]

        id_texto = self.canvas.create_text(x, y, text=texto_exibicao, font=("Segoe UI", 9, "bold"), fill="white", justify="center", tags=("movable", current_node_id))
        
        bbox = self.canvas.bbox(id_texto)
        pad_x, pad_y = 12, 8
        x1, y1 = bbox[0] - pad_x, bbox[1] - pad_y
        x2, y2 = bbox[2] + pad_x, bbox[3] + pad_y
        
        id_rect = self.canvas.create_rectangle(x1, y1, x2, y2, fill=cor_bg, outline=cor_borda, width=1.5, tags=("movable", current_node_id))
        
        self.canvas.tag_lower(id_rect, id_texto)
        
        return current_node_id

    def preencher_plano_execucao(self):
        if not self.arvore_otimizada: return
        plano = gerar_plano_execucao(self.arvore_otimizada)
        
        for i, passo in enumerate(plano, 1):
            partes = passo.split(":", 1)
            operador = partes[0].strip()
            detalhe = partes[1].strip() if len(partes) > 1 else ""
            
            if "Tabela" in operador: tag = 'ler'
            elif "σ" in operador: tag = 'filtro'
            elif "⋈" in operador: tag = 'juncao'
            else: tag = 'projecao'
            
            self.tree.insert("", tk.END, values=(i, operador, detalhe), tags=(tag,))

if __name__ == "__main__":
    janela = ctk.CTk()
    app = SGBDModernApp(janela)
    janela.mainloop()