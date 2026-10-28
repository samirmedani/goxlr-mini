// Peripheriques audio par defaut de Windows, lus et corriges depuis la session de l'utilisateur.
// Le moteur tourne en SYSTEM et ne voit pas ces reglages (ils sont propres a chaque compte) : c'est l'appli qui
// les lit avec IMMDeviceEnumerator et les change avec IPolicyConfig, comme le panneau Son de Windows.
// Cause d'echo la plus frequente : Windows enregistre « Broadcast Stream Mix » au lieu de « Chat Mic ».
using System.Runtime.InteropServices;
using Microsoft.Win32;

namespace GoXLRMini;

static class AudioDefaults
{
    const string Base = @"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio";
    const string DescKey = "{a45c254e-df1c-4efd-8020-67d146a850e0},2";      // PKEY_Device_DeviceDesc (« System », « Chat Mic »)
    const string IfaceKey = "{b3f8fa53-0004-438e-9003-51a46e139bfc},6";     // PKEY_DeviceInterface_FriendlyName
    const string RenderPrefix = "{0.0.0.00000000}.", CapturePrefix = "{0.0.1.00000000}.";
    public const string Mic = "Chat Mic", Sound = "System", Voice = "Chat";
    const int Render = 0, Capture = 1, RoleConsole = 0, RoleMultimedia = 1, RoleComms = 2;

    sealed record Endpoint(string Id, string Name, bool GoXlr);

    static List<Endpoint> Active(int flow)
    {
        var list = new List<Endpoint>();
        using var root = Registry.LocalMachine.OpenSubKey(Base + (flow == Render ? @"\Render" : @"\Capture"));
        if (root == null) return list;
        foreach (var guid in root.GetSubKeyNames())
        {
            using var k = root.OpenSubKey(guid);
            if (k?.GetValue("DeviceState") is not int state || state != 1) continue;      // 1 = DEVICE_STATE_ACTIVE
            using var p = k.OpenSubKey("Properties");
            var name = p?.GetValue(DescKey) as string ?? "";
            var iface = p?.GetValue(IfaceKey) as string ?? "";
            list.Add(new Endpoint((flow == Render ? RenderPrefix : CapturePrefix) + guid, name,
                iface.Contains("GoXLR", StringComparison.OrdinalIgnoreCase)));
        }
        return list;
    }

    static string? DefaultId(int flow, int role)
    {
        try
        {
            var e = (IMMDeviceEnumerator)new MMDeviceEnumeratorCom();
            if (e.GetDefaultAudioEndpoint(flow, role, out var d) != 0 || d == null) return null;
            return d.GetId(out var id) == 0 ? id : null;
        }
        catch { return null; }
    }

    static Endpoint? Find(List<Endpoint> all, string? id) =>
        id == null ? null : all.FirstOrDefault(x => string.Equals(x.Id, id, StringComparison.OrdinalIgnoreCase));

    static object Side(Endpoint? e) => e == null ? new { name = (string?)null, goxlr = false } : new { name = (string?)e.Name, goxlr = e.GoXlr };

    /// Etat envoye a l'interface. issues : ce qui fait de l'echo ou contourne la GoXLR, par role Windows.
    public static Dictionary<string, object?> Status()
    {
        var render = Active(Render);
        var capture = Active(Capture);
        bool goxlr = render.Any(x => x.GoXlr) && capture.Any(x => x.GoXlr && x.Name == Mic);
        var r0 = Find(render, DefaultId(Render, RoleConsole));
        var r2 = Find(render, DefaultId(Render, RoleComms));
        var c0 = Find(capture, DefaultId(Capture, RoleConsole));
        var c2 = Find(capture, DefaultId(Capture, RoleComms));
        var issues = new List<object>();
        if (goxlr)
        {
            foreach (var (e, role) in new[] { (c0, "console"), (c2, "communications") })
            {
                if (e == null) issues.Add(new { kind = "capture-none", role, name = (string?)null });
                else if (e.GoXlr && e.Name != Mic) issues.Add(new { kind = "capture-loop", role, name = (string?)e.Name });
                else if (!e.GoXlr) issues.Add(new { kind = "capture-other", role, name = (string?)e.Name });
            }
            foreach (var (e, role) in new[] { (r0, "console"), (r2, "communications") })
            {
                if (e == null) issues.Add(new { kind = "render-none", role, name = (string?)null });
                else if (!e.GoXlr) issues.Add(new { kind = "render-other", role, name = (string?)e.Name });
            }
        }
        return new Dictionary<string, object?>
        {
            ["type"] = "audio-defaults",
            ["goxlr"] = goxlr,
            ["render"] = new { console = Side(r0), communications = Side(r2) },
            ["capture"] = new { console = Side(c0), communications = Side(c2) },
            ["issues"] = issues,
        };
    }

    /// Corrige seulement ce qui est faux : sortie hors GoXLR -> System (Chat pour les communications),
    /// entree autre que Chat Mic -> Chat Mic. Un choix deja sur la GoXLR (Game, Music...) est garde.
    /// Renvoie le nombre de roles changes, -1 si la GoXLR n'expose pas ses voies.
    public static int Fix()
    {
        var render = Active(Render);
        var capture = Active(Capture);
        var sound = render.FirstOrDefault(x => x.GoXlr && x.Name == Sound);
        var voice = render.FirstOrDefault(x => x.GoXlr && x.Name == Voice) ?? sound;
        var mic = capture.FirstOrDefault(x => x.GoXlr && x.Name == Mic);
        if (sound == null || mic == null) return -1;
        var policy = (IPolicyConfig)new PolicyConfigClient();
        int changed = 0;
        foreach (var role in new[] { RoleConsole, RoleMultimedia, RoleComms })
        {
            var cur = Find(render, DefaultId(Render, role));
            if (cur == null || !cur.GoXlr)
            {
                var want = role == RoleComms ? voice! : sound;
                if (policy.SetDefaultEndpoint(want.Id, role) == 0) changed++;
            }
            var curIn = Find(capture, DefaultId(Capture, role));
            if (curIn == null || !curIn.GoXlr || curIn.Name != Mic)
                if (policy.SetDefaultEndpoint(mic.Id, role) == 0) changed++;
        }
        return changed;
    }

    [ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]
    class MMDeviceEnumeratorCom { }

    [ComImport, Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IMMDeviceEnumerator
    {
        [PreserveSig] int EnumAudioEndpoints(int dataFlow, int stateMask, out IntPtr devices);
        [PreserveSig] int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice device);
    }

    [ComImport, Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IMMDevice
    {
        [PreserveSig] int Activate(ref Guid iid, int clsCtx, IntPtr p, out IntPtr ppv);
        [PreserveSig] int OpenPropertyStore(int access, out IntPtr store);
        [PreserveSig] int GetId([MarshalAs(UnmanagedType.LPWStr)] out string id);
    }

    // Interface non documentee mais stable depuis Windows 7, utilisee par tous les outils de bascule audio.
    [ComImport, Guid("870AF99C-171D-4F9E-AF0D-E63DF40C2BC9")]
    class PolicyConfigClient { }

    [ComImport, Guid("F8679F50-850A-41CF-9C72-430F290290C8"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IPolicyConfig
    {
        [PreserveSig] int GetMixFormat(IntPtr a, IntPtr b);
        [PreserveSig] int GetDeviceFormat(IntPtr a, int b, IntPtr c);
        [PreserveSig] int ResetDeviceFormat(IntPtr a);
        [PreserveSig] int SetDeviceFormat(IntPtr a, IntPtr b, IntPtr c);
        [PreserveSig] int GetProcessingPeriod(IntPtr a, int b, IntPtr c, IntPtr d);
        [PreserveSig] int SetProcessingPeriod(IntPtr a, IntPtr b);
        [PreserveSig] int GetShareMode(IntPtr a, IntPtr b);
        [PreserveSig] int SetShareMode(IntPtr a, IntPtr b);
        [PreserveSig] int GetPropertyValue(IntPtr a, IntPtr b, IntPtr c);
        [PreserveSig] int SetPropertyValue(IntPtr a, IntPtr b, IntPtr c);
        [PreserveSig] int SetDefaultEndpoint([MarshalAs(UnmanagedType.LPWStr)] string id, int role);
        [PreserveSig] int SetEndpointVisibility(IntPtr a, int b);
    }
}
