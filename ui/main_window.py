import tkinter as tk
import math, threading, random, webbrowser
from tkinter import filedialog
import customtkinter as ctk

try:
    from scanner.regex_scanner import scan_text_regex
    from scanner.ner_scanner import scan_text_ner
    from scanner.context_rules import apply_context_rules
    from redactor.text_redactor import redact_text, restore_text
    from sender.autopaste import send_to_ai
    from storage.audit_log import write_log
    from storage.settings_store import load_settings
except ImportError:
    def scan_text_regex(t): return []
    def scan_text_ner(t): return []
    def apply_context_rules(f,t): return f
    def redact_text(t,f): return t,[],{}
    def restore_text(t,m): return t,[]
    def send_to_ai(tool,t): pass
    def write_log(d): pass
    def load_settings(): return {}

BG="#000000";SIDEBAR_BG="#050505";ACCENT="#00f2ff";ACCENT_DIM="#006666"
TEXT_MAIN="#ffffff";TEXT_DIM="#a1a1aa";BORDER="#27272a";INPUT_BG="#18181b"
CARD="#0d0d0d";GREEN="#00ff9d";WHITE="#ffffff"

class MainWindow(ctk.CTkFrame):
    def __init__(self,parent):
        super().__init__(parent,fg_color=BG)
        self.settings=load_settings()
        self.findings=[];self.finding_vars=[];self.restore_map={}
        self.cleaned_text="";self.original_text=""
        self.cubes=[];self.particles=[]

        # 1. Sidebar
        self._build_sidebar()

        # 2. Main container (right of sidebar)
        self.main_container=tk.Frame(self,bg=BG)
        self.main_container.place(x=200,y=0,relwidth=1,relheight=1,width=-200)

        # 3. Canvas for 3D background + chat content
        self.canvas=tk.Canvas(self.main_container,bg=BG,highlightthickness=0,bd=0)
        self.canvas.place(relx=0,rely=0,relwidth=1,relheight=1)

        # 4. Output inner frame embedded in canvas (scrollable chat bubbles)
        self.output_inner=tk.Frame(self.canvas,bg=BG)
        self.output_window=self.canvas.create_window((0,0),window=self.output_inner,anchor="nw")

        # 5. Artifact panel (hidden by default, appears on right like Claude)
        self.artifact_panel=tk.Frame(self.main_container,bg=SIDEBAR_BG,
            highlightbackground=BORDER,highlightthickness=1)

        # 6. Input box overlay
        self._build_input_box()

        # 7. Events
        self.canvas.bind("<Configure>",self._on_canvas_resize)
        self.output_inner.bind("<Configure>",lambda e:self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<MouseWheel>",lambda e:self.canvas.yview_scroll(
            int(-1*(e.delta/120)),"units"))

        self.after(100,self._init_3d)
        self.after(500,self._show_welcome)

    # ── 3D BACKGROUND ──────────────────────────────────────

    def _init_3d(self):
        W,H=self.canvas.winfo_width(),self.canvas.winfo_height()
        if W<10:self.after(100,self._init_3d);return
        for _ in range(25):
            self.cubes.append({
                "x":random.uniform(50,W-50),"y":random.uniform(-H,H),
                "z":random.uniform(50,400),
                "rx":random.random()*6,"ry":random.random()*6,"rz":random.random()*6,
                "dx":random.uniform(0.01,0.03),"dy":random.uniform(0.01,0.03),"dz":random.uniform(0.01,0.03),
                "speed":random.uniform(1.2,2.5),"size":random.uniform(20,45),
                "color":ACCENT if random.random()<0.4 else random.choice([WHITE,"#333333","#555555"])
            })
        self.particles=[{
            "x":random.uniform(0,W),"y":random.uniform(0,H),
            "vx":random.uniform(-0.5,0.5),"vy":random.uniform(-0.5,0.5)
        } for _ in range(60)]
        self._animate_bg()

    def _animate_bg(self):
        c=self.canvas;W,H=c.winfo_width(),c.winfo_height()
        c.delete("3d")
        for i,p in enumerate(self.particles):
            p["x"]=(p["x"]+p["vx"])%W;p["y"]=(p["y"]+p["vy"])%H
            c.create_oval(p["x"]-1,p["y"]-1,p["x"]+1,p["y"]+1,
                fill="#111111",outline="",tags="3d")
            for p2 in self.particles[i+1:i+3]:
                d=math.hypot(p["x"]-p2["x"],p["y"]-p2["y"])
                if d<100:
                    a=int((1-d/100)*20)
                    c.create_line(p["x"],p["y"],p2["x"],p2["y"],
                        fill=f"#{a:02x}{a:02x}{a:02x}",tags="3d")
        edges=[(0,1),(1,2),(2,3),(3,0),(4,5),(5,6),(6,7),(7,4),(0,4),(1,5),(2,6),(3,7)]
        for cb in self.cubes:
            cb["rx"]+=cb["dx"];cb["ry"]+=cb["dy"];cb["rz"]+=cb["dz"]
            cb["y"]+=cb["speed"]
            if cb["y"]>H+80:cb["y"]=-80;cb["x"]=random.uniform(50,W-50)
            nodes=[]
            for i in range(8):
                x=cb["size"]*(1 if i&1 else -1)
                y=cb["size"]*(1 if i&2 else -1)
                z=cb["size"]*(1 if i&4 else -1)
                y,z=y*math.cos(cb["rx"])-z*math.sin(cb["rx"]),y*math.sin(cb["rx"])+z*math.cos(cb["rx"])
                x,z=x*math.cos(cb["ry"])+z*math.sin(cb["ry"]),-x*math.sin(cb["ry"])+z*math.cos(cb["ry"])
                x,y=x*math.cos(cb["rz"])-y*math.sin(cb["rz"]),x*math.sin(cb["rz"])+y*math.cos(cb["rz"])
                f=400/(z+cb["z"]);nodes.append((cb["x"]+x*f,cb["y"]+y*f))
            for e in edges:
                c.create_line(nodes[e[0]],nodes[e[1]],fill=cb["color"],width=1.2,tags="3d")
        c.tag_lower("3d")
        self.after(35,self._animate_bg)

    # ── WELCOME SCREEN ─────────────────────────────────────

    def _show_welcome(self):
        for w in self.output_inner.winfo_children():w.destroy()
        self.canvas.delete("welcome")
        msg=random.choice([
            "What do you want to send to the AI today?",
            "PrivacyGate scans before anything leaves your device.",
            "Paste your message below — we clean it first.",
            "Your data never leaves your machine.",
            "No cloud. No leaks. Just clean AI prompts.",
        ])
        W,H=self.canvas.winfo_width(),self.canvas.winfo_height()
        self.welcome_txt=self.canvas.create_text(W/2,H/2-50,text="",
            font=("Segoe UI",28,"bold"),fill=TEXT_MAIN,
            width=600,justify="center",tags="welcome")
        def type_in(i=0):
            if i<=len(msg):
                self.canvas.itemconfig(self.welcome_txt,text=msg[:i])
                self.after(45,lambda:type_in(i+1))
            else:
                self.after(2000,self._fade_to_logo)
        type_in()

    def _fade_to_logo(self):
        self.canvas.delete("welcome")
        W,H=self.canvas.winfo_width(),self.canvas.winfo_height()
        self.canvas.create_text(W/2,H/2-60,text="PrivacyGate",
            font=("Segoe UI",65,"bold"),fill=ACCENT,tags="welcome")
        self.canvas.create_text(W/2,H/2+20,text="YOUR PRIVATE AI SAFETY LAYER",
            font=("Segoe UI",12,"bold"),fill=TEXT_DIM,tags="welcome")

    # ── SIDEBAR ────────────────────────────────────────────

    def _build_sidebar(self):
        self.sidebar=tk.Frame(self,bg=SIDEBAR_BG,width=200)
        self.sidebar.place(x=0,y=0,width=200,relheight=1)
        tk.Label(self.sidebar,text="P",font=("Segoe UI",28,"bold"),
            fg=ACCENT,bg=SIDEBAR_BG).pack(pady=(40,5))
        self.nav_btns=[]
        for icon,txt,cmd in [("⬡","Scan",self._nav_scan),
                              ("◈","Audit",self._nav_audit),
                              ("◎","Settings",self._nav_settings)]:
            btn=ctk.CTkButton(self.sidebar,text=f"  {icon}   {txt}",
                font=("Segoe UI",13),fg_color="transparent",
                text_color=TEXT_DIM,hover_color="#111111",
                anchor="w",height=45,corner_radius=8,command=cmd)
            btn.pack(fill="x",padx=12,pady=4)
            self.nav_btns.append(btn)
        self._set_nav(0)

    # ── INPUT BOX ──────────────────────────────────────────

    def _build_input_box(self):
        self.input_container=ctk.CTkFrame(self.main_container,
            fg_color=INPUT_BG,corner_radius=28,
            border_width=1,border_color=BORDER)
        self.input_container.place(relx=0.5,rely=0.88,relwidth=0.75,anchor="center")

        inner=tk.Frame(self.input_container,bg=INPUT_BG)
        inner.pack(fill="x",padx=20,pady=12)

        # + attach button
        tk.Button(inner,text="+",font=("Segoe UI",18),fg=TEXT_DIM,bg=INPUT_BG,
            relief="flat",cursor="hand2",
            command=self._show_attach_menu).pack(side="left",padx=(0,15))

        # Text input
        self.message_input=tk.Text(inner,font=("Segoe UI",14),
            fg=TEXT_DIM,bg=INPUT_BG,
            insertbackground=ACCENT,relief="flat",
            height=1,highlightthickness=0,
            selectbackground=ACCENT,selectforeground=BG)
        self.message_input.pack(side="left",fill="x",expand=True)
        self.message_input.insert("1.0","Message PrivacyGate...")
        self.message_input.bind("<FocusIn>",self._clear_ph)
        self.message_input.bind("<FocusOut>",self._restore_ph)
        self.message_input.bind("<Return>",self._on_enter)
        self.message_input.bind("<KeyRelease>",self._auto_resize)

        # Send button
        self.send_btn=ctk.CTkButton(inner,text="↑",
            font=("Segoe UI",18,"bold"),
            fg_color=ACCENT,hover_color=ACCENT_DIM,
            width=38,height=38,corner_radius=19,
            text_color=BG,command=self._start_scan)
        self.send_btn.pack(side="right",padx=(10,0))

    def _auto_resize(self,e=None):
        lines=int(self.message_input.index("end-1c").split(".")[0])
        self.message_input.configure(height=max(1,min(lines,5)))

    # ── ARTIFACT PANEL (Claude-style split) ────────────────

    def _show_artifact_panel(self,text):
        # Shrink canvas to left 55%
        self.canvas.place(relx=0,rely=0,relwidth=0.55,relheight=1)
        # Move input box to fit left side
        self.input_container.place(relx=0.275,rely=0.88,relwidth=0.5,anchor="center")

        # Artifact panel fills right 45%
        self.artifact_panel.place(relx=0.55,rely=0,relwidth=0.45,relheight=1)
        for w in self.artifact_panel.winfo_children():w.destroy()

        # Header
        header=tk.Frame(self.artifact_panel,bg="#111111")
        header.pack(fill="x")
        tk.Label(header,text="  Cleaned Message",
            font=("Segoe UI",11,"bold"),fg=ACCENT,
            bg="#111111",pady=10).pack(side="left")
        btn_f=tk.Frame(header,bg="#111111")
        btn_f.pack(side="right",padx=10)

        def copy_it():
            self.clipboard_clear();self.clipboard_append(text)
            cb.config(text=" ✓ Copied ")
            self.after(2000,lambda:cb.config(text=" Copy "))

        cb=tk.Button(btn_f,text=" Copy ",font=("Segoe UI",9,"bold"),
            fg=TEXT_MAIN,bg="#333333",relief="flat",
            padx=8,cursor="hand2",command=copy_it)
        cb.pack(side="left",padx=2,pady=6)

        tk.Button(btn_f,text=" Share ▾ ",font=("Segoe UI",9,"bold"),
            fg=BG,bg=ACCENT,relief="flat",padx=8,
            cursor="hand2",command=self._show_share_menu).pack(side="left",padx=2,pady=6)

        tk.Button(btn_f,text=" × ",font=("Segoe UI",12),
            fg=TEXT_DIM,bg="#111111",relief="flat",
            cursor="hand2",command=self._close_artifact).pack(side="left",padx=5,pady=6)

        # Divider + filename (like Claude artifact header)
        tk.Frame(self.artifact_panel,bg=BORDER,height=1).pack(fill="x")
        tk.Label(self.artifact_panel,text="  cleaned_message.txt",
            font=("Segoe UI",10),fg="#555555",
            bg=SIDEBAR_BG,pady=6,anchor="w").pack(fill="x")
        tk.Frame(self.artifact_panel,bg=BORDER,height=1).pack(fill="x")

        # Content text area
        txt=tk.Text(self.artifact_panel,font=("Segoe UI",13),
            fg=TEXT_MAIN,bg=SIDEBAR_BG,relief="flat",
            padx=24,pady=20,wrap="word",highlightthickness=0,
            selectbackground=ACCENT,selectforeground=BG)
        txt.pack(fill="both",expand=True)
        txt.insert("1.0",text)
        txt.config(state="disabled")

        # Restore button at bottom
        restore_bar=tk.Frame(self.artifact_panel,bg="#111111")
        restore_bar.pack(fill="x",side="bottom")
        tk.Frame(restore_bar,bg=BORDER,height=1).pack(fill="x")
        tk.Button(restore_bar,text="  Paste AI Response & Restore  →",
            font=("Segoe UI",11,"bold"),fg=TEXT_MAIN,bg="#111111",
            relief="flat",padx=14,pady=10,cursor="hand2",
            command=self._enter_restore_mode).pack(side="left",padx=12,pady=6)

    def _close_artifact(self):
        # Restore canvas to full width
        self.canvas.place(relx=0,rely=0,relwidth=1,relheight=1)
        self.input_container.place(relx=0.5,rely=0.88,relwidth=0.75,anchor="center")
        self.artifact_panel.place_forget()

    # ── SCANNING ───────────────────────────────────────────

    def _on_canvas_resize(self,e):
        self.canvas.itemconfig(self.output_window,width=e.width)

    def _clear_ph(self,e):
        if self.message_input.get("1.0","end-1c").strip()=="Message PrivacyGate...":
            self.message_input.delete("1.0","end")
            self.message_input.config(fg=TEXT_MAIN)
        self.input_container.configure(border_color=ACCENT)

    def _restore_ph(self,e):
        if not self.message_input.get("1.0","end-1c").strip():
            self.message_input.insert("1.0","Message PrivacyGate...")
            self.message_input.config(fg=TEXT_DIM)
        self.input_container.configure(border_color=BORDER)

    def _on_enter(self,e):
        if not e.state&0x1:self._start_scan();return "break"

    def _start_scan(self):
        text=self.message_input.get("1.0","end").strip()
        if not text or text=="Message PrivacyGate...":return
        self.canvas.delete("welcome")
        self.original_text=text
        self._add_user_bubble(text)
        self.message_input.delete("1.0","end")
        self.message_input.config(fg=TEXT_DIM)
        self._add_divider()
        scan_bub=self._add_bubble("🔍  Scanning locally...",color=TEXT_DIM,bg=CARD)
        threading.Thread(target=self._run_scan,args=(text,scan_bub),daemon=True).start()

    def _run_scan(self,text,scan_bub):
        f=[]
        f.extend(scan_text_regex(text))
        f.extend(scan_text_ner(text))
        self.findings=apply_context_rules(f,text)
        self.after(0,lambda:self._show_findings(scan_bub))

    # ── FINDINGS ───────────────────────────────────────────

    def _show_findings(self,scan_bub):
        scan_bub.master.destroy()
        if not self.findings:
            self._add_bubble("✓  No sensitive info found. Safe to send.",color=GREEN,bg=CARD)
            self._show_send_options();return
        self._add_bubble(
            f"Found {len(self.findings)} sensitive item(s).\nGreen = will be redacted. Click to toggle.",
            color=TEXT_MAIN,bg=CARD)
        self.finding_vars=[]
        for f in self.findings:self._add_finding_row(f)
        self._show_finding_actions()

    def _add_finding_row(self,finding):
        var=tk.BooleanVar(value=True)
        self.finding_vars.append((var,finding))
        row=tk.Frame(self.output_inner,bg=INPUT_BG,
            highlightbackground=ACCENT,highlightthickness=1)
        row.pack(fill="x",padx=48,pady=3)
        row.bind("<MouseWheel>",lambda e:self.canvas.yview_scroll(int(-1*(e.delta/120)),"units"))
        chk=tk.Button(row,text="✓",font=("Segoe UI",9,"bold"),
            fg=WHITE,bg=ACCENT,relief="flat",padx=6,pady=3,cursor="hand2")
        def toggle(v=var,r=row,b=chk):
            v.set(not v.get())
            if v.get():b.config(bg=ACCENT,text="✓");r.config(highlightbackground=ACCENT)
            else:b.config(bg=BORDER,text=" ");r.config(highlightbackground=BORDER)
        chk.config(command=toggle);chk.pack(side="left",padx=10,pady=8)
        risk=finding.get("risk","LOW");rc={"HIGH":"#ff4444","MED":ACCENT,"LOW":"#555555"}
        tk.Label(row,text=finding.get("risk","LOW"),font=("Segoe UI",9,"bold"),
            fg=rc.get(risk,"#555"),bg=INPUT_BG,width=5).pack(side="left",padx=(0,6))
        tk.Label(row,text=finding.get("type",""),font=("Segoe UI",10,"bold"),
            fg=TEXT_DIM,bg=INPUT_BG,width=14,anchor="w").pack(side="left")
        tk.Label(row,text=finding.get("value","")[:44],font=("Segoe UI",11),
            fg=TEXT_MAIN,bg=INPUT_BG,anchor="w").pack(side="left",fill="x",expand=True)
        tk.Label(row,text="→",font=("Segoe UI",12),
            fg=BORDER,bg=INPUT_BG).pack(side="left",padx=6)
        tk.Label(row,text=finding.get("replace",""),font=("Segoe UI",11),
            fg=ACCENT,bg=INPUT_BG).pack(side="left",padx=(0,12))

    def _show_finding_actions(self):
        f=tk.Frame(self.output_inner,bg=BG);f.pack(fill="x",padx=48,pady=10)
        tk.Button(f,text=" Send Anyway ",font=("Segoe UI",11),
            fg=TEXT_DIM,bg=CARD,relief="flat",padx=10,pady=6,
            cursor="hand2",command=self._send_anyway).pack(side="left",padx=(0,8))
        tk.Button(f,text=" Clean & Continue → ",font=("Segoe UI",12,"bold"),
            fg=BG,bg=ACCENT,relief="flat",padx=14,pady=7,
            cursor="hand2",command=self._clean_and_continue).pack(side="left")

    # ── CLEAN & SEND ───────────────────────────────────────

    def _clean_and_continue(self):
        checked=[f for v,f in self.finding_vars if v.get()]
        if not checked:
            self._add_bubble("Please check at least one item.",color="#ff4444",bg=CARD);return
        self.cleaned_text,summary,self.restore_map=redact_text(self.original_text,checked)
        write_log({"findings":checked,"tool":"pending"})
        self._add_divider()
        self._add_bubble("✓  Message cleaned. Result on the right →",color=GREEN,bg=CARD)
        for item in summary:
            self._add_bubble(
                f"  {item['type']}:  {item['original']}  →  {item['replace']}",
                color=GREEN,bg="#001a0d")
        # Show Claude-style artifact panel
        self._show_artifact_panel(self.cleaned_text)

    def _send_anyway(self):
        self.cleaned_text=self.original_text;self.restore_map={}
        self._add_bubble("Sending original without redacting.",color=TEXT_DIM,bg=CARD)
        self._show_send_options()

    def _show_send_options(self):
        f=tk.Frame(self.output_inner,bg=BG);f.pack(fill="x",padx=48,pady=10)
        tk.Button(f,text=" Share to AI Tool ▾ ",font=("Segoe UI",12,"bold"),
            fg=BG,bg=ACCENT,relief="flat",padx=15,pady=8,
            cursor="hand2",command=self._show_share_menu).pack(side="left")

    def _show_share_menu(self):
        """Show styled share panel inside artifact panel."""
        # Find artifact panel and add share UI inside it
        # Create overlay share panel
        share=tk.Toplevel(self)
        share.overrideredirect(True)  # No window border
        share.configure(bg="#111111")
        share.attributes("-topmost",True)

        # Position near share button — bottom right of artifact panel
        ap=self.artifact_panel
        x=ap.winfo_rootx()+20
        y=ap.winfo_rooty()+50
        share.geometry(f"320x420+{x}+{y}")

        # Header
        hdr=tk.Frame(share,bg="#1a1a1a");hdr.pack(fill="x")
        tk.Label(hdr,text="  Share to AI Tool",font=("Segoe UI",12,"bold"),
            fg=ACCENT,bg="#1a1a1a",pady=12).pack(side="left")
        tk.Button(hdr,text=" × ",font=("Segoe UI",12),fg=TEXT_DIM,bg="#1a1a1a",
            relief="flat",cursor="hand2",command=share.destroy).pack(side="right",padx=8)
        tk.Frame(share,bg=BORDER,height=1).pack(fill="x")

        # Description
        tk.Label(share,text="Your cleaned message will be copied\nand the AI tool will open in browser.",
            font=("Segoe UI",10),fg=TEXT_DIM,bg="#111111",justify="left").pack(anchor="w",padx=16,pady=(12,8))

        # AI tool buttons
        tools=[
            ("Claude",       "claude.ai",           "#d97706"),
            ("ChatGPT",      "chatgpt.com",          "#10b981"),
            ("Gemini",       "gemini.google.com",    "#3b82f6"),
            ("Copilot",      "copilot.microsoft.com","#8b5cf6"),
            ("Perplexity",   "perplexity.ai",        "#ef4444"),
            ("DeepSeek",     "chat.deepseek.com",    "#06b6d4"),
        ]

        for tool,url,dot_color in tools:
            row=tk.Frame(share,bg="#111111",cursor="hand2")
            row.pack(fill="x",padx=12,pady=3)

            inner=tk.Frame(row,bg="#1c1c1c",pady=8,padx=12,cursor="hand2")
            inner.pack(fill="x")

            # Colored dot
            tk.Label(inner,text="●",font=("Segoe UI",10),
                fg=dot_color,bg="#1c1c1c").pack(side="left",padx=(0,10))

            # Tool name
            tk.Label(inner,text=tool,font=("Segoe UI",12,"bold"),
                fg=TEXT_MAIN,bg="#1c1c1c").pack(side="left")

            # URL label
            tk.Label(inner,text=url,font=("Segoe UI",9),
                fg=TEXT_DIM,bg="#1c1c1c").pack(side="left",padx=(8,0))

            # Open button
            def make_cmd(t=tool,s=share):
                def cmd():
                    self._open_ai_tool(t)
                    s.destroy()
                return cmd

            tk.Button(inner,text="Open →",font=("Segoe UI",9,"bold"),
                fg=BG,bg=ACCENT,relief="flat",padx=8,pady=3,
                cursor="hand2",command=make_cmd()).pack(side="right")

            # Hover effect
            def on_enter(e,f=inner):f.config(bg="#252525")
            def on_leave(e,f=inner):f.config(bg="#1c1c1c")
            inner.bind("<Enter>",on_enter);inner.bind("<Leave>",on_leave)
            for child in inner.winfo_children():
                child.bind("<Enter>",on_enter);child.bind("<Leave>",on_leave)

        # Close when clicking outside
        share.bind("<FocusOut>",lambda e:share.destroy())

    def _open_ai_tool(self,tool):
        urls={"Claude":"https://claude.ai","ChatGPT":"https://chatgpt.com",
              "Gemini":"https://gemini.google.com","Copilot":"https://copilot.microsoft.com",
              "Perplexity":"https://perplexity.ai","DeepSeek":"https://chat.deepseek.com"}
        self.clipboard_clear();self.clipboard_append(self.cleaned_text)
        webbrowser.open(urls.get(tool,"https://google.com"))
        self._add_bubble(f"✓  Opened {tool}. Cleaned message copied to clipboard!",
            color=ACCENT,bg=CARD)

    # ── RESTORE ────────────────────────────────────────────

    def _enter_restore_mode(self):
        self.message_input.delete("1.0","end")
        self.message_input.config(fg=ACCENT)
        self.message_input.insert("1.0","Paste the AI's response here...")
        self.message_input.bind("<FocusIn>",self._clear_restore_ph)
        self.send_btn.configure(text="↩",fg_color="#1a0a2e",
            hover_color="#2d1054",command=self._do_restore)
        self._add_bubble(
            "Restore mode — paste the AI's response in the input box and press ↩",
            color=ACCENT,bg=CARD)

    def _clear_restore_ph(self,e):
        if self.message_input.get("1.0","end-1c").strip()=="Paste the AI's response here...":
            self.message_input.delete("1.0","end")
            self.message_input.config(fg=TEXT_MAIN)

    def _do_restore(self):
        response=self.message_input.get("1.0","end").strip()
        if not response or response=="Paste the AI's response here...":return
        restored,rs=restore_text(response,self.restore_map)
        self.message_input.delete("1.0","end")
        self.message_input.config(fg=TEXT_DIM)
        self.message_input.insert("1.0","Message PrivacyGate...")
        self.message_input.configure(height=1)
        self.send_btn.configure(text="↑",fg_color=ACCENT,
            hover_color=ACCENT_DIM,command=self._start_scan)
        self.message_input.bind("<FocusIn>",self._clear_ph)
        self._add_divider()
        self._add_bubble(f"✓  Restored {len(rs)} placeholder(s) with your real data:",
            color=GREEN,bg=CARD)
        # Show restored result in artifact panel
        self._show_artifact_panel(restored)

    # ── BUBBLES ────────────────────────────────────────────

    def _add_bubble(self,text,color=WHITE,bg=CARD):
        f=tk.Frame(self.output_inner,bg=BG);f.pack(fill="x",padx=32,pady=3)
        bub=tk.Frame(f,bg=bg,padx=14,pady=10);bub.pack(fill="x")
        lbl=tk.Label(bub,text=text,font=("Segoe UI",12),fg=color,bg=bg,
            anchor="w",justify="left",wraplength=500)
        lbl.pack(fill="x")
        for w in [f,bub,lbl]:
            w.bind("<MouseWheel>",lambda e:self.canvas.yview_scroll(
                int(-1*(e.delta/120)),"units"))
        return bub

    def _add_user_bubble(self,text):
        f=tk.Frame(self.output_inner,bg=BG);f.pack(fill="x",padx=32,pady=3)
        bub=tk.Frame(f,bg="#0d1b1b",padx=14,pady=10);bub.pack(side="right")
        tk.Label(bub,text=text[:300]+("..." if len(text)>300 else ""),
            font=("Segoe UI",12),fg=ACCENT,bg="#0d1b1b",
            anchor="w",justify="left",wraplength=460).pack()

    def _add_divider(self):
        tk.Frame(self.output_inner,bg=BORDER,height=1).pack(fill="x",padx=32,pady=10)

    # ── ATTACH ─────────────────────────────────────────────

    def _show_attach_menu(self):
        m=tk.Menu(self,tearoff=0,bg=CARD,fg=WHITE,
            font=("Segoe UI",11),activebackground=ACCENT,activeforeground=BG,bd=0)
        m.add_command(label="📄  Document (PDF / DOCX)",command=self._attach_file)
        m.add_separator()
        m.add_command(label="🖼️  Image (PNG / JPG)",command=self._attach_image)
        try:
            x=self.winfo_rootx()+220
            y=self.winfo_rooty()+self.winfo_height()-150
            m.tk_popup(x,y)
        finally:m.grab_release()

    def _attach_file(self):
        path=filedialog.askopenfilename(title="Select Document",
            filetypes=[("Documents","*.pdf *.docx *.doc"),("All","*.*")])
        if path:
            name=path.replace("\\","/").split("/")[-1]
            self._add_bubble(f"📄  Attached: {name}",color=TEXT_DIM,bg=CARD)

    def _attach_image(self):
        path=filedialog.askopenfilename(title="Select Image",
            filetypes=[("Images","*.png *.jpg *.jpeg *.bmp"),("All","*.*")])
        if path:
            name=path.replace("\\","/").split("/")[-1]
            self._add_bubble(f"🖼️  Attached: {name}",color=TEXT_DIM,bg=CARD)

    # ── NAV HELPERS ────────────────────────────────────────

    def _set_nav(self,idx):
        for i,b in enumerate(self.nav_btns):
            b.configure(text_color=TEXT_MAIN if i==idx else TEXT_DIM,
                fg_color="#0d0d0d" if i==idx else "transparent")

    def _nav_scan(self):
        self._set_nav(0)
        self._close_artifact()
        self._show_welcome()

    def _nav_audit(self):
        self._set_nav(1)
        self.canvas.delete("welcome")
        for w in self.output_inner.winfo_children():w.destroy()
        from storage.audit_log import read_log
        logs=read_log()
        tk.Label(self.output_inner,text="Audit Log",
            font=("Segoe UI",17,"bold"),fg=TEXT_MAIN,bg=BG).pack(anchor="w",padx=36,pady=(24,12))
        if not logs:
            tk.Label(self.output_inner,text="No scans yet.",
                font=("Segoe UI",12),fg=TEXT_DIM,bg=BG).pack(pady=40);return
        for log in logs[:20]:
            row=tk.Frame(self.output_inner,bg=CARD);row.pack(fill="x",padx=36,pady=3)
            tk.Label(row,
                text=f"  {log['timestamp']}   {log['tool']}   {log['total_redacted']} redacted",
                font=("Segoe UI",11),fg=TEXT_DIM,bg=CARD,anchor="w",pady=8).pack(fill="x",padx=8)

    def _nav_settings(self):
        self._set_nav(2)
        self.canvas.delete("welcome")
        for w in self.output_inner.winfo_children():w.destroy()
        tk.Label(self.output_inner,text="Settings",
            font=("Segoe UI",17,"bold"),fg=TEXT_MAIN,bg=BG).pack(anchor="w",padx=36,pady=(24,12))
        tk.Label(self.output_inner,text="Coming soon.",
            font=("Segoe UI",12),fg=TEXT_DIM,bg=BG).pack(pady=40)