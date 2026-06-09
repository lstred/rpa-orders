Add-Type @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public class WinEnum {
  [DllImport("user32.dll")] static extern bool EnumWindows(EnumWindowsProc cb, IntPtr l);
  [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool MoveWindow(IntPtr h,int x,int y,int w,int ht,bool repaint);
  public struct RECT { public int L,T,R,B; }
  delegate bool EnumWindowsProc(IntPtr h, IntPtr l);
  public static List<IntPtr> Handles(uint target) {
    var res = new List<IntPtr>();
    EnumWindows((h,l)=>{ uint pid; GetWindowThreadProcessId(h, out pid); if (pid==target) res.Add(h); return true; }, IntPtr.Zero);
    return res;
  }
  public static string Info(IntPtr h) {
    var sb=new StringBuilder(256); GetWindowText(h,sb,256); RECT r; GetWindowRect(h, out r);
    return h.ToInt64()+" | vis="+IsWindowVisible(h)+" | title='"+sb+"' | rect="+r.L+","+r.T+","+r.R+","+r.B;
  }
}
"@

$proc = Get-Process python,pythonw -ErrorAction SilentlyContinue | Sort-Object StartTime -Descending | Select-Object -First 1
if (-not $proc) { Write-Output "NO_APP_PROCESS"; return }
Write-Output ("PID=" + $proc.Id)
$handles = [WinEnum]::Handles([uint32]$proc.Id)
if ($handles.Count -eq 0) { Write-Output "NO_WINDOWS"; return }
foreach ($h in $handles) {
  Write-Output ([WinEnum]::Info($h))
  # Force any top-level window on-screen, restored, and to the foreground.
  [WinEnum]::MoveWindow($h, 200, 120, 1280, 820, $true) | Out-Null
  [WinEnum]::ShowWindow($h, 9) | Out-Null   # SW_RESTORE
  [WinEnum]::SetForegroundWindow($h) | Out-Null
}
Write-Output "DONE_FOREGROUND"
