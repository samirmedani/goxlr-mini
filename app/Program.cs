// GoXLR Mini - application Windows (logiciel libre, licence MIT).
// Fenetre fixe WebView2 sur l'interface servie par goxlrctl.py (http://127.0.0.1:14565/),
// icone d'etat et menu dans la zone de notification, bulle a l'ecran quand le micro change,
// relance du moteur s'il ne repond plus, relance de l'appli apres une mise a jour. Instance unique.
using System.Diagnostics;
using System.Drawing.Drawing2D;
using System.Drawing.Text;
using System.Runtime.InteropServices;
using System.Text.Json;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;
using Microsoft.Win32;

namespace GoXLRMini;

static class Program
{
    public const string Url = "http://127.0.0.1:14565/";
    public const string TaskName = "GoXLR Mini";
    public const string DataFolder = "GoXLR Mini";
    const string MutexName = @"Local\GoXLRMiniApp";
    public const string ShowEvent = @"Local\GoXLRMiniAppShow";
    public const string CaptureEvent = @"Local\GoXLRMiniAppCapture";
    public static readonly Version AppVersion = typeof(Program).Assembly.GetName().Version ?? new Version(0, 0);

    [STAThread]
    static void Main(string[] args)
    {
        bool startHidden = args.Contains("--tray");
        bool capture = args.Contains("--capture");
        using var mutex = new Mutex(true, MutexName, out bool first);
        if (!first && args.Contains("--relaunch"))
        {
            // relance apres mise a jour : l'ancienne instance rend le verrou en quittant
            try { first = mutex.WaitOne(TimeSpan.FromSeconds(20)); } catch (AbandonedMutexException) { first = true; }
        }
        if (!first)
        {
            // relance ratee (l'ancienne instance n'a pas rendu le verrou) : on s'efface sans rouvrir sa fenetre
            if (!args.Contains("--relaunch"))
                try { using var ev = EventWaitHandle.OpenExisting(capture ? CaptureEvent : ShowEvent); ev.Set(); } catch { }
            return;
        }
        Application.SetHighDpiMode(HighDpiMode.PerMonitorV2);
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        var form = new MainForm(startHidden, capture);
        StartListener(ShowEvent, () => form.ShowFromTray());
        StartListener(CaptureEvent, () => form.CaptureToFile());
        Application.Run(new MiniContext(form, startHidden));
    }

    static void StartListener(string name, Action action)
    {
        var ev = new EventWaitHandle(false, EventResetMode.AutoReset, name);
        var t = new Thread(() => { while (ev.WaitOne()) Ui.Post(action); }) { IsBackground = true };
        t.Start();
    }
}

static class Ui
{
    public static SynchronizationContext? Ctx;
    public static void Post(Action a) => Ctx?.Post(_ => a(), null);
}

sealed class MiniContext : ApplicationContext
{
    public MiniContext(MainForm form, bool hidden)
    {
        Ui.Ctx = SynchronizationContext.Current ?? new WindowsFormsSynchronizationContext();
        form.FormClosed += (_, _) => ExitThread();
        form.PrepareHandles();
        form.InitAsync();
        form.StartMonitor();
        if (!hidden) form.ShowFromTray();
    }
}

sealed class MainForm : Form
{
    const int LogicalW = 1280, LogicalH = 800, MinW = 900, MinH = 620;
    readonly WebView2 web = new();
    readonly NotifyIcon tray = new();
    readonly HttpClient http = new() { Timeout = TimeSpan.FromSeconds(3) };
    readonly ToolStripMenuItem micItem = new("Couper le micro");
    readonly ToolStripMenuItem scenesItem = new("Scènes");
    readonly ToolStripMenuItem startupItem = new("Démarrer avec Windows");
    readonly System.Windows.Forms.Timer monitor = new() { Interval = 1000 };
    readonly bool captureOnLoad;
    readonly Dictionary<string, Icon> icons = new();
    bool quitting, toldTray, webReady, polling;
    string? lastMic;            // etat micro vu au dernier passage ("on", "all", "stream"...)
    string iconKey = "";
    DateTime lastOk = DateTime.UtcNow, lastRescue = DateTime.MinValue;
    Osd? osd;

    public MainForm(bool startHidden, bool capture)
    {
        captureOnLoad = capture;
        Text = "GoXLR Mini";
        var iconPath = Path.Combine(AppContext.BaseDirectory, "app.ico");
        if (File.Exists(iconPath)) Icon = new Icon(iconPath);
        FormBorderStyle = FormBorderStyle.Sizable;           // l'interface s'adapte a la taille de la fenetre
        MaximizeBox = true;
        StartPosition = FormStartPosition.CenterScreen;
        BackColor = Color.FromArgb(245, 245, 247);
        ShowInTaskbar = true;
        web.Dock = DockStyle.Fill;
        web.DefaultBackgroundColor = Color.FromArgb(245, 245, 247);
        Controls.Add(web);
        SizeToDpi(initial: true);
        BuildIcons();
        BuildTray();
    }

    public void PrepareHandles()
    {
        _ = Handle;
        _ = web.Handle;
    }

    void SizeToDpi(bool initial)
    {
        float scale = DeviceDpi / 96f;
        MinimumSize = SizeFromClientSize(new Size((int)Math.Round(MinW * scale), (int)Math.Round(MinH * scale)));
        if (initial) ClientSize = new Size((int)Math.Round(LogicalW * scale), (int)Math.Round(LogicalH * scale));
    }

    protected override void OnDpiChanged(DpiChangedEventArgs e)
    {
        base.OnDpiChanged(e);
        SizeToDpi(initial: false);
    }

    protected override void OnHandleCreated(EventArgs e)
    {
        base.OnHandleCreated(e);
        Native.LightTitleBar(Handle);
    }

    // ---------- WebView2 ----------
    public async void InitAsync()
    {
        try
        {
            var data = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), Program.DataFolder, "WebView2");
            var env = await CoreWebView2Environment.CreateAsync(null, data);
            await web.EnsureCoreWebView2Async(env);
            var s = web.CoreWebView2.Settings;
            s.AreDefaultContextMenusEnabled = false;
            s.AreDevToolsEnabled = Environment.GetEnvironmentVariable("GOXLR_DEVTOOLS") == "1";
            s.IsZoomControlEnabled = false;
            s.IsPinchZoomEnabled = false;
            s.IsStatusBarEnabled = false;
            s.AreBrowserAcceleratorKeysEnabled = false;
            s.IsSwipeNavigationEnabled = false;
            web.CoreWebView2.NewWindowRequested += (_, e) =>
            {
                e.Handled = true;           // liens externes (GitHub, notes de version) : navigateur par defaut
                if (Uri.TryCreate(e.Uri, UriKind.Absolute, out var u) && u.Scheme == Uri.UriSchemeHttps)
                    try { Process.Start(new ProcessStartInfo(u.AbsoluteUri) { UseShellExecute = true }); } catch { }
            };
            web.CoreWebView2.PermissionRequested += (_, e) =>
            {
                // « M'écouter » enregistre l'entree Chat Mic : seule la page locale du moteur a le micro, rien d'autre
                bool local = e.Uri.StartsWith(Program.Url, StringComparison.OrdinalIgnoreCase);
                e.State = local && e.PermissionKind == CoreWebView2PermissionKind.Microphone
                    ? CoreWebView2PermissionState.Allow : CoreWebView2PermissionState.Deny;
            };
            web.CoreWebView2.NavigationCompleted += async (_, e) =>
            {
                if (!e.IsSuccess) { await Task.Delay(1500); await LoadUiAsync(); return; }
                if (web.Source?.ToString().StartsWith(Program.Url) == true)
                {
                    webReady = true;
                    if (captureOnLoad) { await Task.Delay(1500); CaptureToFile(); }
                }
            };
            web.CoreWebView2.NavigateToString(SplashHtml);
            await LoadUiAsync();
        }
        catch (Exception ex)
        {
            MessageBox.Show("Le moteur d'affichage WebView2 est introuvable.\n\n" + ex.Message, "GoXLR Mini", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    async Task<bool> DaemonUp()
    {
        try { using var r = await http.GetAsync(Program.Url + "api/live"); return r.IsSuccessStatusCode; }
        catch { return false; }
    }

    async Task LoadUiAsync()
    {
        if (!await DaemonUp())
        {
            RunTask();
            for (int i = 0; i < 40 && !await DaemonUp(); i++) await Task.Delay(500);
        }
        web.CoreWebView2.Navigate(Program.Url);
    }

    async Task RunScript(string js)
    {
        if (web.CoreWebView2 == null || !webReady) return;
        try { await web.CoreWebView2.ExecuteScriptAsync(js); } catch { }
    }

    public async void CaptureToFile()
    {
        if (web.CoreWebView2 == null) return;
        var dir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), Program.DataFolder);
        Directory.CreateDirectory(dir);
        var pageFile = Path.Combine(dir, "capture-page.txt");
        if (webReady && File.Exists(pageFile))
        {
            var p = File.ReadAllText(pageFile).Trim();
            if (p == "diag") { await web.CoreWebView2.ExecuteScriptAsync("openDiag()"); await Task.Delay(1500); }
            else if (p.Length > 0 && p.All(char.IsLetter)) { await web.CoreWebView2.ExecuteScriptAsync("closeSheet(); go('" + p + "')"); await Task.Delay(900); }
        }
        var tmp = Path.Combine(dir, "capture.tmp");
        using (var fs = File.Create(tmp))
            await web.CoreWebView2.CapturePreviewAsync(CoreWebView2CapturePreviewImageFormat.Png, fs);
        File.Move(tmp, Path.Combine(dir, "capture.png"), true);
    }

    // ---------- surveillance du moteur (icone, bulle, relance) ----------
    public void StartMonitor()
    {
        monitor.Tick += async (_, _) => await Poll();
        monitor.Start();
    }

    async Task Poll()
    {
        if (polling) return;
        polling = true;
        try
        {
            using var doc = JsonDocument.Parse(await http.GetStringAsync(Program.Url + "api/live"));
            var root = doc.RootElement;
            lastOk = DateTime.UtcNow;
            bool connected = root.GetProperty("connected").GetBoolean();
            string health = root.TryGetProperty("health", out var hv) && hv.ValueKind == JsonValueKind.String ? hv.GetString() ?? "ok" : "ok";
            string mic = "on";
            if (root.TryGetProperty("mic", out var m))
            {
                if (m.GetProperty("muted").GetBoolean()) mic = "all";
                else if (m.GetProperty("partial").ValueKind == JsonValueKind.String) mic = m.GetProperty("partial").GetString() ?? "on";
            }
            bool osdOn = !root.TryGetProperty("osd", out var o) || o.ValueKind != JsonValueKind.False;
            if (root.TryGetProperty("app_version", out var av) && av.ValueKind == JsonValueKind.String) RelaunchIfUpdated(av.GetString());
            SetIcon(!connected || health != "ok" ? "off" : mic == "on" ? "on" : mic == "all" ? "muted" : "part",
                    !connected ? (health == "absent" ? "GoXLR Mini · débranchée" : "GoXLR Mini · reconnexion…")
                    : mic == "on" ? "GoXLR Mini · micro actif" : mic == "all" ? "GoXLR Mini · micro coupé" : "GoXLR Mini · micro " + MicLabel(mic));
            if (lastMic != null && mic != lastMic && connected && osdOn) ShowOsd(mic);
            if (connected) lastMic = mic;
        }
        catch
        {
            SetIcon("off", "GoXLR Mini · moteur arrêté");
            var down = DateTime.UtcNow - lastOk;
            if (down > TimeSpan.FromSeconds(20) && DateTime.UtcNow - lastRescue > TimeSpan.FromSeconds(60))
            {
                lastRescue = DateTime.UtcNow;
                if (down > TimeSpan.FromSeconds(50)) KillEngine();      // moteur fige : on le coupe avant de relancer
                RunTask();
            }
        }
        finally { polling = false; }
    }

    static string MicLabel(string t) => t switch
    {
        "stream" => "coupé du stream", "chat" => "coupé de Discord", "phones" => "coupé du casque",
        "lineout" => "coupé des enceintes", "all" => "coupé", _ => "actif"
    };

    /// Apres une mise a jour, le moteur annonce la nouvelle version et le fichier de l'appli a deja ete remplace
    /// (l'ancien a ete deplace dans backup) : on relance le nouvel exe dans le meme etat (fenetre ou icone seule).
    /// La version installee se lit dans manifest.json : FileVersionInfo sur notre propre exe renvoie la version
    /// de l'image deja chargee en memoire, pas celle du nouveau fichier.
    bool relaunching;
    void RelaunchIfUpdated(string? engineVersion)
    {
        if (relaunching || quitting || !Version.TryParse(engineVersion, out var ev)) return;
        if (ev <= Program.AppVersion) return;
        var exe = Environment.ProcessPath;
        if (exe == null || !File.Exists(exe)) return;
        var onDisk = InstalledVersion(exe);
        if (onDisk == null || onDisk <= Program.AppVersion) return;
        relaunching = true;
        try
        {
            Process.Start(new ProcessStartInfo(exe, Visible ? "--relaunch" : "--tray --relaunch") { UseShellExecute = false, WorkingDirectory = Path.GetDirectoryName(exe) });
            Quit();
        }
        catch { relaunching = false; }
    }

    static Version? InstalledVersion(string exe)
    {
        try
        {
            var root = Path.GetDirectoryName(Path.GetDirectoryName(exe));
            if (root == null) return null;
            using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(root, "manifest.json")));
            return Version.TryParse(doc.RootElement.GetProperty("version").GetString(), out var v) ? v : null;
        }
        catch { return null; }
    }

    void ShowOsd(string mic)
    {
        osd ??= new Osd();
        if (mic == "on") osd.Flash("Micro actif", "Tout le monde t'entend", Color.FromArgb(48, 209, 88));
        else if (mic == "all") osd.Flash("Micro coupé", "Personne ne t'entend", Color.FromArgb(255, 69, 58));
        else osd.Flash("Micro " + MicLabel(mic), "Les autres t'entendent encore", Color.FromArgb(255, 159, 10));
    }

    static void RunTask()
    {
        try { Process.Start(new ProcessStartInfo("schtasks", "/run /tn \"" + Program.TaskName + "\"") { CreateNoWindow = true, UseShellExecute = false }); } catch { }
    }

    static void KillEngine()
    {
        var dir = AppContext.BaseDirectory.TrimEnd('\\');
        var root = Path.GetDirectoryName(dir) ?? dir;
        foreach (var name in new[] { "pythonw", "python" })
            foreach (var p in Process.GetProcessesByName(name))
            {
                try { if (p.MainModule?.FileName?.StartsWith(root, StringComparison.OrdinalIgnoreCase) == true) p.Kill(); } catch { }
            }
    }

    // ---------- icones d'etat ----------
    void BuildIcons()
    {
        var baseIcon = Icon ?? SystemIcons.Application;
        icons["on"] = Badge(baseIcon, null);
        icons["muted"] = Badge(baseIcon, Color.FromArgb(255, 69, 58));
        icons["part"] = Badge(baseIcon, Color.FromArgb(255, 159, 10));
        icons["off"] = Badge(baseIcon, Color.FromArgb(142, 142, 147));
    }

    static Icon Badge(Icon src, Color? c)
    {
        const int S = 32;
        using var bmp = new Bitmap(S, S);
        using (var g = Graphics.FromImage(bmp))
        {
            g.SmoothingMode = SmoothingMode.AntiAlias;
            using var ico = new Icon(src, S, S);
            g.DrawIcon(ico, new Rectangle(0, 0, S, S));
            if (c != null)
            {
                var r = new RectangleF(S - 17, S - 17, 16, 16);
                using var ring = new SolidBrush(Color.FromArgb(20, 20, 24));
                g.FillEllipse(ring, RectangleF.Inflate(r, 1.5f, 1.5f));
                using var b = new SolidBrush(c.Value);
                g.FillEllipse(b, r);
                using var pen = new Pen(Color.White, 2.2f) { StartCap = LineCap.Round, EndCap = LineCap.Round };
                g.DrawLine(pen, r.Left + 4.5f, r.Top + 4.5f, r.Right - 4.5f, r.Bottom - 4.5f);
            }
        }
        var h = bmp.GetHicon();
        var icon = (Icon)Icon.FromHandle(h).Clone();
        Native.DestroyIcon(h);
        return icon;
    }

    void SetIcon(string key, string text)
    {
        if (iconKey != key) { tray.Icon = icons[key]; iconKey = key; }
        if (tray.Text != text) tray.Text = text.Length > 63 ? text[..63] : text;
    }

    // ---------- fenetre et zone de notification ----------
    public void ShowFromTray()
    {
        if (!Visible) Show();
        if (WindowState == FormWindowState.Minimized) WindowState = FormWindowState.Normal;
        Activate();
    }

    protected override void OnFormClosing(FormClosingEventArgs e)
    {
        if (!quitting && e.CloseReason == CloseReason.UserClosing)
        {
            e.Cancel = true;
            Hide();
            if (!toldTray)
            {
                toldTray = true;
                tray.ShowBalloonTip(2500, "GoXLR Mini", "L'appli reste disponible ici, en bas à droite.", ToolTipIcon.None);
            }
            return;
        }
        tray.Visible = false;
        base.OnFormClosing(e);
    }

    void Quit()
    {
        quitting = true;
        tray.Visible = false;
        Close();
    }

    void BuildTray()
    {
        tray.Icon = icons["off"];
        iconKey = "off";
        tray.Text = "GoXLR Mini";
        var menu = new ContextMenuStrip { Renderer = new MenuRenderer(), ShowImageMargin = false, ShowCheckMargin = true, Font = new Font("Segoe UI", 10f), Padding = new Padding(4) };
        var open = new ToolStripMenuItem("Ouvrir GoXLR Mini", null, (_, _) => ShowFromTray()) { Font = new Font("Segoe UI Semibold", 10f) };
        micItem.Click += async (_, _) => await ToggleMic();
        startupItem.Click += (_, _) => { SetStartup(!startupItem.Checked); startupItem.Checked = IsStartup(); };
        menu.Items.Add(open);
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add(micItem);
        menu.Items.Add(scenesItem);
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add(new ToolStripMenuItem("Reconnecter la GoXLR", null, async (_, _) => await Post("reconnect", new { })));
        menu.Items.Add(new ToolStripMenuItem("Diagnostic…", null, async (_, _) => { ShowFromTray(); await RunScript("openDiag()"); }));
        menu.Items.Add(startupItem);
        menu.Items.Add(new ToolStripMenuItem("Quitter l'appli", null, (_, _) => Quit()));
        menu.Opening += async (_, _) => await RefreshMenu();
        menu.Opened += (_, _) => Native.RoundCorners(menu.Handle);
        scenesItem.DropDown.Opened += (_, _) => Native.RoundCorners(scenesItem.DropDown.Handle);
        tray.ContextMenuStrip = menu;
        tray.MouseClick += (_, e) => { if (e.Button == MouseButtons.Left) ShowFromTray(); };
        tray.Visible = true;
        startupItem.Checked = IsStartup();
    }

    async Task RefreshMenu()
    {
        try
        {
            using var doc = JsonDocument.Parse(await http.GetStringAsync(Program.Url + "api/state"));
            var root = doc.RootElement;
            var st = root.GetProperty("state");
            bool micMuted = st.GetProperty("mutes").GetProperty("Mic").GetBoolean()
                || (st.TryGetProperty("partial", out var pa) && pa.GetProperty("Mic").ValueKind == JsonValueKind.String);
            micItem.Text = micMuted ? "Réactiver le micro" : "Couper le micro";
            micItem.Checked = micMuted;
            micItem.Enabled = true;
            string? active = st.GetProperty("scene").ValueKind == JsonValueKind.String ? st.GetProperty("scene").GetString() : null;
            scenesItem.DropDownItems.Clear();
            foreach (var sc in root.GetProperty("meta").GetProperty("scenes").EnumerateObject())
                scenesItem.DropDownItems.Add(SceneItem(sc.Name, sc.Value.GetProperty("label").GetString() ?? sc.Name, active));
            var mine = st.GetProperty("user_scenes").EnumerateObject().ToList();
            if (mine.Count > 0)
            {
                scenesItem.DropDownItems.Add(new ToolStripSeparator());
                foreach (var sc in mine) scenesItem.DropDownItems.Add(SceneItem(sc.Name, sc.Name, active));
            }
            scenesItem.Enabled = true;
        }
        catch
        {
            micItem.Enabled = false;
            scenesItem.Enabled = false;
        }
    }

    ToolStripMenuItem SceneItem(string name, string label, string? active)
    {
        var it = new ToolStripMenuItem(label) { Checked = name == active };
        it.Click += async (_, _) => await Post("scene", new { name });
        return it;
    }

    async Task ToggleMic() => await Post("mute", new { channel = "Mic", muted = !micItem.Checked, target = "all" });

    async Task Post(string action, object body)
    {
        try
        {
            using var req = new HttpRequestMessage(HttpMethod.Post, Program.Url + "api/" + action)
            {
                Content = new StringContent(JsonSerializer.Serialize(body), System.Text.Encoding.UTF8, "application/json")
            };
            req.Headers.Add("X-GoXLR", "1");
            using var r = await http.SendAsync(req);
        }
        catch { }
    }

    const string RunKey = @"Software\Microsoft\Windows\CurrentVersion\Run";
    static bool IsStartup()
    {
        using var k = Registry.CurrentUser.OpenSubKey(RunKey);
        return k?.GetValue("GoXLR Mini") != null;
    }
    static void SetStartup(bool on)
    {
        using var k = Registry.CurrentUser.CreateSubKey(RunKey);
        if (on) k.SetValue("GoXLR Mini", "\"" + Environment.ProcessPath + "\" --tray");
        else k.DeleteValue("GoXLR Mini", false);
    }

    const string SplashHtml = "<html><body style='margin:0;background:#09090c;display:grid;place-items:center;height:100vh;font-family:Segoe UI Variable Display,Segoe UI,sans-serif;color:#8e8e93'>" +
        "<div style='text-align:center'><div style='width:28px;height:28px;margin:0 auto 16px;border-radius:50%;border:3px solid #333;border-top-color:#0A84FF;animation:s .8s linear infinite'></div>Démarrage de GoXLR Mini…</div>" +
        "<style>@keyframes s{to{transform:rotate(360deg)}}</style></body></html>";
}

/// Bulle a l'ecran : jamais active, jamais de focus, traversee par la souris, au-dessus des jeux en fenetre.
sealed class Osd : Form
{
    readonly System.Windows.Forms.Timer timer = new() { Interval = 30 };
    string title = "", sub = "";
    Color accent = Color.White;
    int ticks;

    public Osd()
    {
        FormBorderStyle = FormBorderStyle.None;
        ShowInTaskbar = false;
        TopMost = true;
        StartPosition = FormStartPosition.Manual;
        BackColor = Color.FromArgb(28, 28, 32);
        DoubleBuffered = true;
        timer.Tick += (_, _) =>
        {
            ticks++;
            if (ticks < 45) return;                              // ~1,4 s visible
            Opacity = Math.Max(0, Opacity - 0.08);
            if (Opacity <= 0.01) { timer.Stop(); Hide(); }
        };
    }

    protected override bool ShowWithoutActivation => true;

    protected override CreateParams CreateParams
    {
        get
        {
            var cp = base.CreateParams;
            cp.ExStyle |= 0x08000000 | 0x00000080 | 0x00000020 | 0x00000008; // NOACTIVATE | TOOLWINDOW | TRANSPARENT | TOPMOST
            return cp;
        }
    }

    public void Flash(string t, string s, Color c)
    {
        title = t; sub = s; accent = c;
        float k = DeviceDpi / 96f;
        Size = new Size((int)(330 * k), (int)(74 * k));
        var wa = Screen.PrimaryScreen?.WorkingArea ?? new Rectangle(0, 0, 1920, 1080);
        Location = new Point(wa.Left + (wa.Width - Width) / 2, wa.Bottom - Height - (int)(64 * k));
        Region = new Region(Native.RoundRect(new Rectangle(0, 0, Width, Height), (int)(22 * k)));
        ticks = 0;
        Opacity = 0.96;
        if (!Visible) Native.ShowNoActivate(this);
        Invalidate();
        timer.Start();
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        var g = e.Graphics;
        g.SmoothingMode = SmoothingMode.AntiAlias;
        g.TextRenderingHint = TextRenderingHint.ClearTypeGridFit;
        float k = DeviceDpi / 96f;
        var dot = new RectangleF(18 * k, (Height - 40 * k) / 2, 40 * k, 40 * k);
        using (var b = new SolidBrush(accent)) g.FillEllipse(b, dot);
        using (var pen = new Pen(Color.White, 2.4f * k) { StartCap = LineCap.Round, EndCap = LineCap.Round })
        {
            float cx = dot.X + dot.Width / 2, cy = dot.Y + dot.Height / 2;
            g.DrawArc(pen, cx - 7 * k, cy - 6 * k, 14 * k, 14 * k, 20, 140);
            g.DrawLine(pen, cx, cy + 8 * k, cx, cy + 11 * k);
            using var cap = new GraphicsPath();
            cap.AddArc(cx - 3.5f * k, cy - 11 * k, 7 * k, 7 * k, 180, 180);
            cap.AddArc(cx - 3.5f * k, cy - 1 * k, 7 * k, 7 * k, 0, 180);
            cap.CloseFigure();
            g.DrawPath(pen, cap);
            if (accent.R > 200 && accent.G < 120) g.DrawLine(pen, cx - 10 * k, cy - 10 * k, cx + 10 * k, cy + 10 * k);
        }
        using var f1 = new Font("Segoe UI Semibold", 13f);
        using var f2 = new Font("Segoe UI", 9.5f);
        using var w = new SolidBrush(Color.FromArgb(245, 245, 247));
        using var gr = new SolidBrush(Color.FromArgb(160, 160, 168));
        g.DrawString(title, f1, w, 70 * k, 14 * k);
        g.DrawString(sub, f2, gr, 71 * k, 40 * k);
    }
}

/// Menu de la zone de notification, dans le style de l'interface : fond clair, survol bleu.
sealed class MenuRenderer : ToolStripProfessionalRenderer
{
    public MenuRenderer() : base(new MenuColors()) { RoundedEdges = true; }
    protected override void OnRenderItemText(ToolStripItemTextRenderEventArgs e)
    {
        e.TextColor = !e.Item.Enabled ? Color.FromArgb(142, 142, 147) : e.Item.Selected ? Color.White : Color.FromArgb(29, 29, 31);
        base.OnRenderItemText(e);
    }
    protected override void OnRenderArrow(ToolStripArrowRenderEventArgs e)
    {
        e.ArrowColor = e.Item != null && e.Item.Selected ? Color.White : Color.FromArgb(110, 110, 115);
        base.OnRenderArrow(e);
    }
    protected override void OnRenderItemCheck(ToolStripItemImageRenderEventArgs e)
    {
        var r = e.ImageRectangle;
        using var pen = new Pen(e.Item.Selected ? Color.White : Color.FromArgb(0, 113, 227), 2f) { StartCap = LineCap.Round, EndCap = LineCap.Round };
        e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
        e.Graphics.DrawLines(pen, new[] { new PointF(r.Left + r.Width * .2f, r.Top + r.Height * .52f), new PointF(r.Left + r.Width * .42f, r.Top + r.Height * .74f), new PointF(r.Left + r.Width * .8f, r.Top + r.Height * .3f) });
    }
}

sealed class MenuColors : ProfessionalColorTable
{
    static readonly Color Bg = Color.FromArgb(250, 250, 252), Sel = Color.FromArgb(0, 113, 227), Line = Color.FromArgb(226, 226, 231);
    public override Color ToolStripDropDownBackground => Bg;
    public override Color ImageMarginGradientBegin => Bg;
    public override Color ImageMarginGradientMiddle => Bg;
    public override Color ImageMarginGradientEnd => Bg;
    public override Color MenuBorder => Line;
    public override Color MenuItemBorder => Sel;
    public override Color MenuItemSelected => Sel;
    public override Color MenuItemSelectedGradientBegin => Sel;
    public override Color MenuItemSelectedGradientEnd => Sel;
    public override Color MenuItemPressedGradientBegin => Sel;
    public override Color MenuItemPressedGradientEnd => Sel;
    public override Color SeparatorDark => Line;
    public override Color SeparatorLight => Line;
    public override Color CheckBackground => Bg;
    public override Color CheckSelectedBackground => Sel;
    public override Color CheckPressedBackground => Sel;
}

static class Native
{
    [DllImport("dwmapi.dll")]
    static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr, ref int value, int size);
    [DllImport("user32.dll")]
    public static extern bool DestroyIcon(IntPtr h);
    [DllImport("user32.dll")]
    static extern bool ShowWindow(IntPtr h, int cmd);
    [DllImport("user32.dll")]
    static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint flags);

    /// Barre de titre de la couleur du fond de l'interface (#F5F5F7), texte #1D1D1F.
    public static void LightTitleBar(IntPtr h)
    {
        int off = 0, caption = 0x00F7F5F5, textColor = 0x001F1D1D;
        DwmSetWindowAttribute(h, 20, ref off, 4);       // DWMWA_USE_IMMERSIVE_DARK_MODE
        DwmSetWindowAttribute(h, 35, ref caption, 4);   // DWMWA_CAPTION_COLOR
        DwmSetWindowAttribute(h, 36, ref textColor, 4); // DWMWA_TEXT_COLOR
    }

    public static void RoundCorners(IntPtr h)
    {
        int round = 2;
        DwmSetWindowAttribute(h, 33, ref round, 4);     // DWMWA_WINDOW_CORNER_PREFERENCE
    }

    /// Affiche sans activer ni voler le premier plan (SW_SHOWNOACTIVATE + HWND_TOPMOST sans SWP_NOACTIVATE oublie).
    public static void ShowNoActivate(Form f)
    {
        ShowWindow(f.Handle, 4);                                            // SW_SHOWNOACTIVATE
        SetWindowPos(f.Handle, new IntPtr(-1), f.Left, f.Top, f.Width, f.Height, 0x0010 | 0x0040); // TOPMOST, NOACTIVATE | SHOWWINDOW
        f.Visible = true;
    }

    public static GraphicsPath RoundRect(Rectangle r, int radius)
    {
        var p = new GraphicsPath();
        int d = radius * 2;
        p.AddArc(r.Left, r.Top, d, d, 180, 90);
        p.AddArc(r.Right - d, r.Top, d, d, 270, 90);
        p.AddArc(r.Right - d, r.Bottom - d, d, d, 0, 90);
        p.AddArc(r.Left, r.Bottom - d, d, d, 90, 90);
        p.CloseFigure();
        return p;
    }
}
