// Joue un fichier son dans une voie precise de la GoXLR (sans changer la sortie par defaut de Windows).
// Usage : audiotest.exe play <Game|Music|System|Chat|Sample> <fichier.wav>
//         audiotest.exe list
using NAudio.CoreAudioApi;
using NAudio.Wave;

var en = new MMDeviceEnumerator();
if (args.Length == 0 || args[0] == "list")
{
    foreach (var d in en.EnumerateAudioEndPoints(DataFlow.All, DeviceState.Active))
        Console.WriteLine($"{d.DataFlow,-7} {d.FriendlyName}");
    return 0;
}
var name = args[1];
var dev = en.EnumerateAudioEndPoints(DataFlow.Render, DeviceState.Active)
    .FirstOrDefault(d => d.FriendlyName.StartsWith(name + " (") && d.FriendlyName.Contains("GoXLR"));
if (dev == null) { Console.WriteLine("voie introuvable : " + name); return 2; }
using var reader = new AudioFileReader(args[2]);
using var outp = new WasapiOut(dev, AudioClientShareMode.Shared, false, 80);
outp.Init(reader);
outp.Play();
while (outp.PlaybackState == PlaybackState.Playing) Thread.Sleep(30);
Console.WriteLine("joue sur " + dev.FriendlyName);
return 0;
