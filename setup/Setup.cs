// GoXLR Mini - installeur Windows (logiciel libre, licence MIT).
// Un seul exe : il embarque GoXLR-Mini.zip, l'extrait dans %TEMP% et lance install.ps1 avec les droits
// administrateur (demandes au clic sur Installer), pour le compte qui a ouvert l'installeur.
//   GoXLR-Mini-Setup.exe                                                  fenetre d'installation
//   GoXLR-Mini-Setup.exe /quiet [/user=COMPTE] [/nodesktop] [/nostartup]  sans fenetre ; code 0 si c'est installe
//   GoXLR-Mini-Setup.exe --capture image.png [--state welcome|working|done|failed] [--dark] [--scale 1.5]
//   GoXLR-Mini-Setup.exe --selftest image.png [/user=COMPTE]   parcours de la fenetre sans clic (tests sur le PC)
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.Drawing.Text;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Principal;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Win32;

namespace GoXLRMiniSetup
{
    static class Program
    {
        public const string Repo = "https://github.com/samirmedani/goxlr-mini";
        public static readonly string Version = VersionText();
        public static readonly string InstallDir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "GoXLR Mini");
        public static string AppExe => Path.Combine(InstallDir, "app", "GoXLR Mini.exe");

        static string VersionText()
        {
            var v = Assembly.GetExecutingAssembly().GetName().Version;
            return v.Major + "." + v.Minor + "." + v.Build;
        }

        [STAThread]
        static int Main(string[] args)
        {
            string Opt(string name) => args.FirstOrDefault(x => x.StartsWith(name + "=", StringComparison.OrdinalIgnoreCase))?.Substring(name.Length + 1).Trim('"');
            bool Has(string name) => args.Any(x => string.Equals(x, name, StringComparison.OrdinalIgnoreCase));
            int Index(string name) => Array.FindIndex(args, x => string.Equals(x, name, StringComparison.OrdinalIgnoreCase));

            if (Has("/quiet") || Has("--quiet"))
                return Quiet(args, Opt("/user"), !Has("/nodesktop"), !Has("/nostartup"));

            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            int cap = Index("--capture");
            if (cap >= 0 && cap + 1 < args.Length)
            {
                int st = Index("--state"), sc = Index("--scale");
                var state = st >= 0 && st + 1 < args.Length ? args[st + 1] : "welcome";
                float scale = sc >= 0 && sc + 1 < args.Length && float.TryParse(args[sc + 1], System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var f) ? f : 1f;
                using (var form = new SetupForm(Has("--dark") ? true : Has("--light") ? false : (bool?)null))
                    form.CaptureTo(args[cap + 1], state, scale);
                return 0;
            }
            int self = Index("--selftest");
            var main = new SetupForm(null) { ForUser = Opt("/user"), SelfTest = self >= 0 && self + 1 < args.Length ? args[self + 1] : null };
            Application.Run(main);
            return main.SelfTest == null ? 0 : main.Succeeded ? 0 : 1;
        }

        public static bool IsAdmin() => new WindowsPrincipal(WindowsIdentity.GetCurrent()).IsInRole(WindowsBuiltInRole.Administrator);

        static int Quiet(string[] args, string user, bool desktop, bool startup)
        {
            user = string.IsNullOrEmpty(user) ? WindowsIdentity.GetCurrent().Name : user;
            if (!IsAdmin())
            {
                var rest = string.Join(" ", args.Where(a => !a.StartsWith("/user=", StringComparison.OrdinalIgnoreCase)).Select(Installer.Quote));
                var psi = new ProcessStartInfo(Application.ExecutablePath, rest + " " + Installer.Quote("/user=" + user)) { UseShellExecute = true, Verb = "runas" };
                try { using (var p = Process.Start(psi)) { p.WaitForExit(); return p.ExitCode; } }
                catch (Win32Exception) { return 1223; }
            }
            var inst = new Installer();
            if (!inst.HasPayload) return 2;
            try
            {
                inst.Extract(null);
                var psi = inst.Command(user, desktop, startup, launch: true);
                psi.UseShellExecute = false;
                psi.CreateNoWindow = true;
                int code;
                using (var p = Process.Start(psi)) { p.WaitForExit(); code = p.ExitCode; }
                if (code == 0) try { Directory.Delete(inst.Dir, true); } catch { }
                return code;
            }
            catch { return 1; }
        }
    }

    /// Extraction du paquet embarque et commande install.ps1.
    sealed class Installer
    {
        public readonly string Dir = Path.Combine(Path.GetTempPath(), "GoXLR-Mini-Setup-" + Program.Version);
        public string StatusPath => Path.Combine(Dir, "status.txt");
        public bool HasPayload => Assembly.GetExecutingAssembly().GetManifestResourceInfo("payload.zip") != null;

        public static string Quote(string s) => "\"" + s.Replace("\"", "\\\"") + "\"";

        public void Extract(Action<double> progress)
        {
            if (Directory.Exists(Dir)) Directory.Delete(Dir, true);
            Directory.CreateDirectory(Dir);
            string root = Path.GetFullPath(Dir).TrimEnd('\\') + "\\";
            using (var s = Assembly.GetExecutingAssembly().GetManifestResourceStream("payload.zip"))
            using (var z = new ZipArchive(s, ZipArchiveMode.Read))
            {
                int n = z.Entries.Count, i = 0;
                foreach (var e in z.Entries)
                {
                    i++;
                    if (string.IsNullOrEmpty(e.Name)) continue;
                    string target = Path.GetFullPath(Path.Combine(Dir, e.FullName.Replace('/', '\\')));
                    if (!target.StartsWith(root, StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("Chemin refuse dans le paquet : " + e.FullName);
                    Directory.CreateDirectory(Path.GetDirectoryName(target));
                    e.ExtractToFile(target, true);
                    if (progress != null && i % 16 == 0) progress(i / (double)n);
                }
            }
            progress?.Invoke(1);
        }

        public ProcessStartInfo Command(string user, bool desktop, bool startup, bool launch)
        {
            string ps = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), @"WindowsPowerShell\v1.0\powershell.exe");
            string a = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File " + Quote(Path.Combine(Dir, "install.ps1"))
                     + " -Quiet -StatusFile " + Quote(StatusPath) + " -ForUser " + Quote(user);
            if (!desktop) a += " -NoDesktop";
            if (!startup) a += " -NoStartup";
            if (!launch) a += " -NoLaunch";
            return new ProcessStartInfo(ps, a) { WorkingDirectory = Dir };
        }

        public string[] ReadStatus()
        {
            try
            {
                using (var f = new FileStream(StatusPath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
                using (var r = new StreamReader(f, true))
                    return r.ReadToEnd().Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries);
            }
            catch { return new string[0]; }
        }

        public static string InstalledVersion()
        {
            try
            {
                using (var hk = RegistryKey.OpenBaseKey(RegistryHive.LocalMachine, RegistryView.Registry64))
                using (var k = hk.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\Uninstall\GoXLRMini"))
                    return k?.GetValue("DisplayVersion") as string;
            }
            catch { return null; }
        }

        public static bool DriverPresent() => File.Exists(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), @"TC-Helicon\GoXLR_Audio_Driver\x64\goxlr_audioapi_x64.dll"));
        public static bool UtilityRunning() => Process.GetProcessesByName("goxlr-daemon").Length + Process.GetProcessesByName("goxlr-utility").Length > 0;
    }

    sealed class Palette
    {
        public Color Bg, Text, Sub, Accent, AccentHover, Button, ButtonHover, ButtonText, SwitchOff, SwitchOn, Warn, Error, Success, Track, Knob;
        public static Palette Get(bool dark) => dark
            ? new Palette { Bg = C(0x1C1C1E), Text = C(0xF5F5F7), Sub = C(0x98989D), Accent = C(0x0A84FF), AccentHover = C(0x409CFF), Button = C(0x3A3A3C), ButtonHover = C(0x48484A), ButtonText = C(0xF5F5F7), SwitchOff = C(0x39393D), SwitchOn = C(0x30D158), Warn = C(0xFF9F0A), Error = C(0xFF453A), Success = C(0x30D158), Track = C(0x3A3A3C), Knob = Color.White }
            : new Palette { Bg = C(0xF5F5F7), Text = C(0x1D1D1F), Sub = C(0x6E6E73), Accent = C(0x0071E3), AccentHover = C(0x0077ED), Button = C(0xE3E3E8), ButtonHover = C(0xD8D8DE), ButtonText = C(0x1D1D1F), SwitchOff = C(0xE5E5EA), SwitchOn = C(0x34C759), Warn = C(0xC93400), Error = C(0xD70015), Success = C(0x248A3D), Track = C(0xE5E5EA), Knob = Color.White };
        static Color C(int rgb) => Color.FromArgb(255, (rgb >> 16) & 255, (rgb >> 8) & 255, rgb & 255);
    }

    sealed class SetupForm : Form
    {
        enum State { Welcome, Working, Done, Failed }
        const int W = 560, H = 380, Pad = 36;

        readonly Installer inst = new Installer();
        readonly bool dark;
        readonly Palette c;
        readonly Bitmap logo;
        string installed = Installer.InstalledVersion();
        bool driverMissing = !Installer.DriverPresent();
        bool utilityRunning = Installer.UtilityRunning();
        State state = State.Welcome;
        float s = 1f;
        bool desktop = true, startup = true;
        double progress;
        string step = "", error = "", engine = "", note = "";
        readonly List<KeyValuePair<RectangleF, string>> hits = new List<KeyValuePair<RectangleF, string>>();
        string hover, pressed;
        public string ForUser, SelfTest;
        public bool Succeeded => state == State.Done;

        public SetupForm(bool? forceDark)
        {
            dark = forceDark ?? SystemDark();
            c = Palette.Get(dark);
            using (var st = Assembly.GetExecutingAssembly().GetManifestResourceStream("app.ico"))
            using (var ico = new Icon(st, 256, 256))
            {
                logo = ico.ToBitmap();
                st.Position = 0;
                Icon = new Icon(st);
            }
            Text = "Installer GoXLR Mini";
            FormBorderStyle = FormBorderStyle.FixedSingle;
            MaximizeBox = false;
            StartPosition = FormStartPosition.CenterScreen;
            BackColor = c.Bg;
            DoubleBuffered = true;
            KeyPreview = true;
            Font = new Font("Segoe UI", 9f);
        }

        static bool SystemDark()
        {
            try { return (int)(Registry.GetValue(@"HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize", "AppsUseLightTheme", 1) ?? 1) == 0; }
            catch { return false; }
        }

        [DllImport("dwmapi.dll")] static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr, ref int value, int size);

        protected override void OnHandleCreated(EventArgs e)
        {
            base.OnHandleCreated(e);
            int on = dark ? 1 : 0;
            DwmSetWindowAttribute(Handle, 20, ref on, 4);          // barre de titre sombre ou claire
            int round = 2;
            DwmSetWindowAttribute(Handle, 33, ref round, 4);       // coins arrondis (Windows 11)
        }

        protected override void OnLoad(EventArgs e)
        {
            base.OnLoad(e);
            s = DeviceDpi / 96f;
            ClientSize = new Size((int)(W * s), (int)(H * s));
            CenterToScreen();
            if (!inst.HasPayload) { state = State.Failed; error = "Cet installeur ne contient pas le paquet GoXLR Mini. Télécharge-le depuis la page des releases."; }
        }

        // ---------- dessin ----------
        Font F(float px, FontStyle style = FontStyle.Regular, bool display = false)
        {
            string fam = display ? (HasFont("Segoe UI Variable Display") ? "Segoe UI Variable Display" : "Segoe UI Semibold")
                                 : (HasFont("Segoe UI Variable Text") ? "Segoe UI Variable Text" : "Segoe UI");
            if (display && fam == "Segoe UI Semibold") style &= ~FontStyle.Bold;
            return new Font(fam, px * s, style, GraphicsUnit.Pixel);
        }
        static readonly Dictionary<string, bool> fonts = new Dictionary<string, bool>();
        static bool HasFont(string name)
        {
            if (fonts.TryGetValue(name, out var ok)) return ok;
            using (var f = new Font(name, 10f)) ok = f.Name == name;
            return fonts[name] = ok;
        }
        RectangleF R(float x, float y, float w, float h) => new RectangleF(x * s, y * s, w * s, h * s);

        static GraphicsPath Round(RectangleF r, float rad)
        {
            var p = new GraphicsPath();
            float d = Math.Min(rad * 2, Math.Min(r.Width, r.Height));
            p.AddArc(r.X, r.Y, d, d, 180, 90);
            p.AddArc(r.Right - d, r.Y, d, d, 270, 90);
            p.AddArc(r.Right - d, r.Bottom - d, d, d, 0, 90);
            p.AddArc(r.X, r.Bottom - d, d, d, 90, 90);
            p.CloseFigure();
            return p;
        }

        void Txt(Graphics g, string t, Font f, Color col, RectangleF r, StringAlignment h = StringAlignment.Near, StringAlignment v = StringAlignment.Near)
        {
            using (var b = new SolidBrush(col))
            using (var sf = new StringFormat(StringFormat.GenericTypographic) { Alignment = h, LineAlignment = v, Trimming = StringTrimming.EllipsisWord })
                g.DrawString(t, f, b, r, sf);
        }

        void Button(Graphics g, string id, string label, RectangleF r, bool primary)
        {
            hits.Add(new KeyValuePair<RectangleF, string>(r, id));
            bool hot = hover == id;
            var fill = primary ? (hot ? c.AccentHover : c.Accent) : (hot ? c.ButtonHover : c.Button);
            if (pressed == id) fill = ControlPaint.Dark(fill, 0.05f);
            using (var p = Round(r, 8 * s)) using (var b = new SolidBrush(fill)) g.FillPath(b, p);
            using (var f = F(14, FontStyle.Bold)) Txt(g, label, f, primary ? Color.White : c.ButtonText, r, StringAlignment.Center, StringAlignment.Center);
        }

        void Switch(Graphics g, string id, string label, string sub, float y, bool on)
        {
            var row = R(Pad, y, W - 2 * Pad, 40);
            hits.Add(new KeyValuePair<RectangleF, string>(row, id));
            using (var f = F(14)) Txt(g, label, f, c.Text, R(Pad, y + 1, W - 2 * Pad - 70, 20));
            using (var f = F(12)) Txt(g, sub, f, c.Sub, R(Pad, y + 21, W - 2 * Pad - 70, 18));
            var track = R(W - Pad - 44, y + 8, 44, 26);
            using (var p = Round(track, 13 * s)) using (var b = new SolidBrush(on ? c.SwitchOn : c.SwitchOff)) g.FillPath(b, p);
            float kx = on ? track.Right - 24 * s : track.X + 2 * s;
            var knob = new RectangleF(kx, track.Y + 2 * s, 22 * s, 22 * s);
            using (var sh = new SolidBrush(Color.FromArgb(dark ? 90 : 40, 0, 0, 0))) g.FillEllipse(sh, new RectangleF(knob.X, knob.Y + 1 * s, knob.Width, knob.Height));
            using (var b = new SolidBrush(c.Knob)) g.FillEllipse(b, knob);
        }

        void Link(Graphics g, string id, string label, RectangleF r, Color col)
        {
            hits.Add(new KeyValuePair<RectangleF, string>(r, id));
            using (var f = F(12, hover == id ? FontStyle.Underline : FontStyle.Regular)) Txt(g, label, f, col, r, StringAlignment.Near, StringAlignment.Center);
        }

        void Badge(Graphics g, bool ok, float x, float y, float size)
        {
            var r = R(x, y, size, size);
            using (var b = new SolidBrush(ok ? c.Success : c.Error)) g.FillEllipse(b, r);
            using (var pen = new Pen(Color.White, 3.2f * s) { StartCap = LineCap.Round, EndCap = LineCap.Round, LineJoin = LineJoin.Round })
            {
                float u = size * s / 56f;
                if (ok) g.DrawLines(pen, new[] { new PointF(r.X + 17 * u, r.Y + 29 * u), new PointF(r.X + 25 * u, r.Y + 37 * u), new PointF(r.X + 40 * u, r.Y + 20 * u) });
                else { g.DrawLine(pen, r.X + 28 * u, r.Y + 15 * u, r.X + 28 * u, r.Y + 32 * u); g.FillEllipse(Brushes.White, r.X + 25.8f * u, r.Y + 38 * u, 4.4f * u, 4.4f * u); }
            }
        }

        protected override void OnPaint(PaintEventArgs e) => Render(e.Graphics);

        void Render(Graphics g)
        {
            hits.Clear();
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.InterpolationMode = InterpolationMode.HighQualityBicubic;
            g.PixelOffsetMode = PixelOffsetMode.HighQuality;
            g.TextRenderingHint = TextRenderingHint.AntiAliasGridFit;
            g.Clear(c.Bg);

            if (state == State.Done || state == State.Failed) Badge(g, state == State.Done, Pad, Pad + 8, 56);
            else g.DrawImage(logo, R(Pad, Pad, 72, 72));

            string title, sub;
            switch (state)
            {
                case State.Working: title = "Installation…"; sub = step; break;
                case State.Done: title = "GoXLR Mini est prêt"; sub = "Version " + Program.Version + " installée"; break;
                case State.Failed: title = "L’installation n’a pas abouti"; sub = "Tes réglages sont gardés. Tu peux réessayer."; break;
                default:
                    title = "GoXLR Mini";
                    sub = installed == null ? "Version " + Program.Version
                        : installed == Program.Version ? "Version " + Program.Version + " · déjà installée"
                        : "Mise à jour " + installed + " → " + Program.Version;
                    break;
            }
            using (var f = F(26, FontStyle.Bold, display: true)) Txt(g, title, f, c.Text, R(Pad + 92, Pad + 10, W - 2 * Pad - 92, 34));
            using (var f = F(13)) Txt(g, sub, f, c.Sub, R(Pad + 92, Pad + 46, W - 2 * Pad - 92, 20));

            float by = H - Pad - 38;
            if (state == State.Welcome)
            {
                using (var f = F(14)) Txt(g, "Pilote ta GoXLR Mini avec le pilote officiel. Le moteur démarre avec Windows, l’appli se range dans la zone de notification.", f, c.Text, R(Pad, 130, W - 2 * Pad, 42));
                Switch(g, "desktop", "Raccourci sur le Bureau", "Le menu Démarrer a toujours le sien.", 186, desktop);
                Switch(g, "startup", "Ouvrir l’appli avec Windows", "Icône d’état et bulle quand le micro change.", 232, startup);
                string warn = driverMissing ? "Pilote GoXLR introuvable : installe-le d’abord." : utilityRunning ? "GoXLR Utility est ouvert : ferme-le avant d’installer." : note;
                if (!string.IsNullOrEmpty(warn))
                {
                    using (var f = F(12)) Txt(g, warn, f, driverMissing || utilityRunning ? c.Warn : c.Sub, R(Pad, 282, W - 2 * Pad - 110, 18));
                    if (driverMissing) Link(g, "driver", "Où le trouver", R(W - Pad - 100, 282, 100, 18), c.Accent);
                }
                string go = installed == null ? "Installer" : installed == Program.Version ? "Réinstaller" : "Mettre à jour";
                Button(g, "install", go, R(W - Pad - 150, by, 150, 38), true);
                Button(g, "close", "Annuler", R(W - Pad - 150 - 12 - 110, by, 110, 38), false);
                Link(g, "repo", "Logiciel libre · GitHub", R(Pad, by, 180, 38), c.Sub);
            }
            else if (state == State.Working)
            {
                var track = R(Pad, 168, W - 2 * Pad, 8);
                using (var p = Round(track, 4 * s)) using (var b = new SolidBrush(c.Track)) g.FillPath(b, p);
                var bar = new RectangleF(track.X, track.Y, Math.Max(track.Height, (float)(track.Width * Math.Min(1, progress))), track.Height);
                using (var p = Round(bar, 4 * s)) using (var b = new SolidBrush(c.Accent)) g.FillPath(b, p);
                using (var f = F(12)) Txt(g, "Windows peut te demander l’autorisation d’installer. Ne débranche pas la GoXLR.", f, c.Sub, R(Pad, 190, W - 2 * Pad, 18));
            }
            else if (state == State.Done)
            {
                using (var f = F(14)) Txt(g, engine, f, c.Text, R(Pad, 130, W - 2 * Pad, 64));
                Button(g, "open", "Ouvrir GoXLR Mini", R(W - Pad - 180, by, 180, 38), true);
                Button(g, "close", "Fermer", R(W - Pad - 180 - 12 - 110, by, 110, 38), false);
            }
            else
            {
                using (var f = F(14)) Txt(g, error, f, c.Text, R(Pad, 130, W - 2 * Pad, 96));
                if (inst.HasPayload)
                {
                    Button(g, "install", "Réessayer", R(W - Pad - 150, by, 150, 38), true);
                    if (Directory.Exists(inst.Dir)) Link(g, "log", "Ouvrir le dossier d’installation", R(Pad, by, 240, 38), c.Sub);
                }
                Button(g, "close", "Fermer", R(W - Pad - (inst.HasPayload ? 150 + 12 + 110 : 110), by, 110, 38), false);
            }
        }

        // ---------- souris et clavier ----------
        string HitAt(Point p) => hits.LastOrDefault(h => h.Key.Contains(p)).Value;

        protected override void OnMouseMove(MouseEventArgs e)
        {
            base.OnMouseMove(e);
            var h = HitAt(e.Location);
            if (h != hover) { hover = h; Cursor = h != null ? Cursors.Hand : Cursors.Default; Invalidate(); }
        }
        protected override void OnMouseLeave(EventArgs e) { base.OnMouseLeave(e); hover = null; Invalidate(); }
        protected override void OnMouseDown(MouseEventArgs e) { base.OnMouseDown(e); pressed = HitAt(e.Location); Invalidate(); }
        protected override void OnMouseUp(MouseEventArgs e)
        {
            base.OnMouseUp(e);
            var h = HitAt(e.Location);
            bool same = h != null && h == pressed;
            pressed = null;
            Invalidate();
            if (same) Act(h);
        }
        protected override void OnKeyDown(KeyEventArgs e)
        {
            base.OnKeyDown(e);
            if (e.KeyCode == Keys.Enter) Act(state == State.Welcome || state == State.Failed ? "install" : state == State.Done ? "open" : null);
            else if (e.KeyCode == Keys.Escape && state != State.Working) Close();
        }
        protected override void OnFormClosing(FormClosingEventArgs e)
        {
            if (state == State.Working && e.CloseReason == CloseReason.UserClosing) e.Cancel = true;
            base.OnFormClosing(e);
        }

        static void Open(string url) { try { Process.Start(new ProcessStartInfo(url) { UseShellExecute = true }); } catch { } }

        async void Act(string id)
        {
            switch (id)
            {
                case "desktop": desktop = !desktop; Invalidate(); break;
                case "startup": startup = !startup; Invalidate(); break;
                case "repo": Open(Program.Repo); break;
                case "driver": Open(Program.Repo + "#installer"); break;
                case "log": Open(inst.Dir); break;
                case "close": Close(); break;
                case "open":
                    try { Process.Start(new ProcessStartInfo(Program.AppExe) { UseShellExecute = true, WorkingDirectory = Path.GetDirectoryName(Program.AppExe) }); } catch { }
                    Close();
                    break;
                case "install":
                    if (state != State.Working && inst.HasPayload) await Install();
                    break;
            }
        }

        static readonly Dictionary<string, KeyValuePair<double, string>> Steps = new Dictionary<string, KeyValuePair<double, string>>
        {
            ["stop"] = new KeyValuePair<double, string>(0.36, "Arrêt de la version en place…"),
            ["copy"] = new KeyValuePair<double, string>(0.48, "Copie des fichiers…"),
            ["task"] = new KeyValuePair<double, string>(0.66, "Moteur lancé avec Windows…"),
            ["links"] = new KeyValuePair<double, string>(0.74, "Raccourcis…"),
            ["start"] = new KeyValuePair<double, string>(0.80, "Démarrage du moteur…"),
        };

        async Task Install()
        {
            state = State.Working; progress = 0.02; step = "Préparation des fichiers…"; error = ""; note = "";
            Invalidate();
            try
            {
                await Task.Run(() => inst.Extract(p => { progress = 0.02 + 0.30 * p; BeginInvoke((Action)Invalidate); }));
                var psi = inst.Command(string.IsNullOrEmpty(ForUser) ? WindowsIdentity.GetCurrent().Name : ForUser, desktop, startup, launch: false);
                psi.UseShellExecute = true;
                psi.WindowStyle = ProcessWindowStyle.Hidden;
                if (!Program.IsAdmin()) psi.Verb = "runas";
                step = "Autorisation de Windows…";
                Invalidate();
                Process p;
                try { p = Process.Start(psi); }
                catch (Win32Exception w) when (w.NativeErrorCode == 1223)
                {
                    state = State.Welcome; note = "Installation annulée : Windows n’a pas reçu ton autorisation.";
                    Invalidate();
                    return;
                }
                string last = "";
                while (!p.HasExited)
                {
                    await Task.Delay(150);
                    last = Apply(inst.ReadStatus(), last);
                    if (last == "start" && progress < 0.97) progress += 0.004;     // le moteur peut mettre quelques secondes
                    Invalidate();
                }
                var lines = inst.ReadStatus();
                Apply(lines, last);
                var end = lines.LastOrDefault(l => l.StartsWith("ok|") || l.StartsWith("error|"));
                if (p.ExitCode == 0 && end != null && end.StartsWith("ok|"))
                {
                    progress = 1;
                    string how = end.Substring(3);
                    engine = how == "connected" ? "Le moteur tourne et ta GoXLR Mini est connectée. Il démarrera tout seul avec Windows."
                           : how == "absent" ? "Le moteur tourne. Branche ta GoXLR Mini : elle sera reprise toute seule."
                           : "Le moteur finit de démarrer. Il démarrera tout seul avec Windows.";
                    state = State.Done;
                    try { Directory.Delete(inst.Dir, true); } catch { }
                }
                else
                {
                    state = State.Failed;
                    error = end != null && end.StartsWith("error|") ? end.Substring(6) : "L’installeur s’est arrêté (code " + p.ExitCode + ").";
                }
            }
            catch (Exception ex)
            {
                state = State.Failed;
                error = ex.Message;
            }
            Invalidate();
        }

        string Apply(string[] lines, string last)
        {
            foreach (var l in lines)
            {
                if (Steps.TryGetValue(l, out var st) && st.Key > progress - 0.0001)
                {
                    progress = Math.Max(progress, st.Key);
                    step = st.Value;
                    last = l;
                }
            }
            return last;
        }

        protected override async void OnShown(EventArgs e)
        {
            base.OnShown(e);
            if (SelfTest == null) return;
            if (inst.HasPayload) await Install();
            Save(SelfTest);
            Close();
        }

        void Save(string path)
        {
            using (var bmp = new Bitmap((int)(W * s), (int)(H * s)))
            {
                using (var g = Graphics.FromImage(bmp)) Render(g);
                bmp.Save(path, ImageFormat.Png);
            }
        }

        // ---------- capture sans fenetre (documentation, verification a distance) ----------
        public void CaptureTo(string path, string which, float scale)
        {
            s = scale;
            installed = null; driverMissing = false; utilityRunning = false;     // ecran d'une premiere installation
            switch (which)
            {
                case "working": state = State.Working; progress = 0.58; step = "Copie des fichiers…"; break;
                case "done": state = State.Done; engine = "Le moteur tourne et ta GoXLR Mini est connectée. Il démarrera tout seul avec Windows."; break;
                case "failed": state = State.Failed; error = "Le moteur ne répond pas. Journal : C:\\ProgramData\\GoXLR Mini\\goxlrctl.log"; break;
                default: state = State.Welcome; break;
            }
            Save(path);
        }
    }
}
