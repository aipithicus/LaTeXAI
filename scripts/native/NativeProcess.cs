using System;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading.Tasks;
using Microsoft.Win32.SafeHandles;

namespace LaTeXAI.Dev
{
    // Small standalone supervisor: direct developer commands do not depend on CDXSCI.
    public sealed class NativeProcess : IDisposable
    {
        private IntPtr job, process;
        public int Id { get; private set; }
        public Capture StdOut { get; private set; }
        public Capture StdErr { get; private set; }
        public bool HasExited => process != IntPtr.Zero && WaitForSingleObject(process, 0) == 0;
        public int? ExitCode => HasExited && GetExitCodeProcess(process, out uint value) ? (int)value : (int?)null;
        public bool TreeReleased
        {
            get
            {
                var accounting = new JobAccounting();
                return job != IntPtr.Zero && QueryInformationJobObject(job, 1, ref accounting,
                    Marshal.SizeOf<JobAccounting>(), IntPtr.Zero) && accounting.ActiveProcesses == 0;
            }
        }

        public static NativeProcess Start(string executable, string[] arguments, string cwd,
            string stdoutPath, string stderrPath, int captureLimit)
        {
            if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException("LaTeXAI native supervision requires Windows");
            var owner = new NativeProcess();
            IntPtr inputRead = IntPtr.Zero, inputWrite = IntPtr.Zero, outputRead = IntPtr.Zero,
                outputWrite = IntPtr.Zero, errorRead = IntPtr.Zero, errorWrite = IntPtr.Zero,
                attributes = IntPtr.Zero, handles = IntPtr.Zero, jobValue = IntPtr.Zero;
            var pi = new ProcessInformation();
            bool initialized = false;
            try
            {
                owner.job = CreateJobObjectW(IntPtr.Zero, null);
                if (owner.job == IntPtr.Zero) Fail("CreateJobObject");
                var limits = new JobLimits();
                limits.Basic.LimitFlags = 0x2000; // KILL_ON_JOB_CLOSE
                if (!SetInformationJobObject(owner.job, 9, ref limits, Marshal.SizeOf<JobLimits>())) Fail("SetInformationJobObject");
                Pipe(out inputRead, out inputWrite, true);
                Pipe(out outputRead, out outputWrite, false);
                Pipe(out errorRead, out errorWrite, false);
                Close(ref inputWrite); // Native stdin is EOF; no interactive input contract.
                IntPtr size = IntPtr.Zero;
                InitializeProcThreadAttributeList(IntPtr.Zero, 2, 0, ref size);
                attributes = Marshal.AllocHGlobal(size);
                if (!InitializeProcThreadAttributeList(attributes, 2, 0, ref size)) Fail("InitializeProcThreadAttributeList");
                initialized = true;
                handles = Marshal.AllocHGlobal(3 * IntPtr.Size);
                Marshal.Copy(new[] { inputRead, outputWrite, errorWrite }, 0, handles, 3);
                if (!UpdateProcThreadAttribute(attributes, 0, new IntPtr(0x20002), handles,
                    new IntPtr(3 * IntPtr.Size), IntPtr.Zero, IntPtr.Zero)) Fail("handle inheritance list");
                // Atomic assignment at creation prevents an uncontained child on admission failure.
                jobValue = Marshal.AllocHGlobal(IntPtr.Size);
                Marshal.WriteIntPtr(jobValue, owner.job);
                if (!UpdateProcThreadAttribute(attributes, 0, new IntPtr(0x2000D), jobValue,
                    new IntPtr(IntPtr.Size), IntPtr.Zero, IntPtr.Zero)) Fail("job assignment list");
                var startup = new StartupEx {
                    Startup = new Startup { Size = Marshal.SizeOf<StartupEx>(), Flags = 0x100,
                        Input = inputRead, Output = outputWrite, Error = errorWrite },
                    Attributes = attributes };
                var command = new StringBuilder(Quote(executable));
                foreach (string arg in arguments) command.Append(' ').Append(Quote(arg));
                if (!CreateProcessW(executable, command, IntPtr.Zero, IntPtr.Zero, true,
                    0x08080004, IntPtr.Zero, string.IsNullOrEmpty(cwd) ? null : cwd, ref startup, out pi)) Fail("CreateProcess");
                owner.process = pi.Process;
                owner.Id = pi.Id;
                Close(ref inputRead); Close(ref outputWrite); Close(ref errorWrite);
                owner.StdOut = new Capture(outputRead, stdoutPath, captureLimit);
                outputRead = IntPtr.Zero;
                owner.StdErr = new Capture(errorRead, stderrPath, captureLimit);
                errorRead = IntPtr.Zero;
                if (ResumeThread(pi.Thread) == uint.MaxValue) Fail("ResumeThread");
                return owner;
            }
            catch { owner.Dispose(); throw; }
            finally
            {
                Close(ref pi.Thread);
                if (initialized) DeleteProcThreadAttributeList(attributes);
                if (attributes != IntPtr.Zero) Marshal.FreeHGlobal(attributes);
                if (handles != IntPtr.Zero) Marshal.FreeHGlobal(handles);
                if (jobValue != IntPtr.Zero) Marshal.FreeHGlobal(jobValue);
                Close(ref inputRead); Close(ref inputWrite); Close(ref outputRead);
                Close(ref outputWrite); Close(ref errorRead); Close(ref errorWrite);
            }
        }

        public void Wait(int milliseconds) { WaitForSingleObject(process, (uint)Math.Max(milliseconds, 0)); }
        public void Stop() { if (job != IntPtr.Zero && !TerminateJobObject(job, 1)) Fail("TerminateJobObject"); }
        public void Dispose()
        {
            // Closing the job kills the complete tree, including during pipeline cancellation.
            Close(ref job);
            Close(ref process);
        }

        public sealed class Capture
        {
            private readonly object gate = new object();
            private readonly MemoryStream retained = new MemoryStream();
            private readonly int limit;
            private long observed;
            public Task Completion { get; private set; }
            public bool EndOfStream { get; private set; }
            public string Failure { get; private set; }
            public long Bytes { get { lock (gate) return observed; } }
            public bool Truncated => Bytes > limit;
            public string Text { get { lock (gate) return Encoding.UTF8.GetString(retained.ToArray()); } }
            internal Capture(IntPtr read, string path, int limit)
            {
                this.limit = Math.Max(limit, 0);
                var pipe = new FileStream(new SafeFileHandle(read, true), FileAccess.Read);
                Completion = Task.Run(() => {
                    try
                    {
                        using (pipe)
                        using (FileStream file = OpenOutput(path))
                        {
                            var buffer = new byte[65536];
                            int count;
                            while ((count = pipe.Read(buffer, 0, buffer.Length)) != 0)
                            {
                                lock (gate)
                                {
                                    observed += count;
                                    int keep = (int)Math.Min(count, this.limit - retained.Length);
                                    retained.Write(buffer, 0, keep);
                                }
                                if (file != null) { file.Write(buffer, 0, count); file.Flush(); }
                            }
                            EndOfStream = true;
                        }
                    }
                    catch (Exception error) { Failure = error.Message; }
                });
            }
            private static FileStream OpenOutput(string path)
            {
                if (string.IsNullOrEmpty(path)) return null;
                string parent = Path.GetDirectoryName(Path.GetFullPath(path));
                Directory.CreateDirectory(parent);
                return new FileStream(path, FileMode.Create, FileAccess.Write, FileShare.Read);
            }
        }

        private static void Fail(string operation) { throw new Win32Exception(Marshal.GetLastWin32Error(), operation); }
        private static void Close(ref IntPtr handle) { if (handle != IntPtr.Zero) { CloseHandle(handle); handle = IntPtr.Zero; } }
        private static void Pipe(out IntPtr read, out IntPtr write, bool parentWrites)
        {
            var security = new Security { Size = Marshal.SizeOf<Security>(), Inherit = true };
            if (!CreatePipe(out read, out write, ref security, 0)) Fail("CreatePipe");
            if (!SetHandleInformation(parentWrites ? write : read, 1, 0)) Fail("SetHandleInformation");
        }
        private static string Quote(string arg)
        {
            var result = new StringBuilder("\"");
            int slashes = 0;
            foreach (char c in arg)
            {
                if (c == '\\') { slashes++; continue; }
                result.Append('\\', c == '"' ? slashes * 2 + 1 : slashes).Append(c);
                slashes = 0;
            }
            return result.Append('\\', slashes * 2).Append('"').ToString();
        }
        [StructLayout(LayoutKind.Sequential)] private struct Security { public int Size; public IntPtr Descriptor; [MarshalAs(UnmanagedType.Bool)] public bool Inherit; }
        [StructLayout(LayoutKind.Sequential)] private struct Startup {
            public int Size; public IntPtr Reserved, Desktop, Title;
            public int X, Y, XSize, YSize, XChars, YChars, Fill; public uint Flags;
            public ushort Show, ReservedSize; public IntPtr Reserved2, Input, Output, Error;
        }
        [StructLayout(LayoutKind.Sequential)] private struct StartupEx { public Startup Startup; public IntPtr Attributes; }
        [StructLayout(LayoutKind.Sequential)] private struct ProcessInformation { public IntPtr Process, Thread; public int Id, ThreadId; }
        [StructLayout(LayoutKind.Sequential)] private struct BasicLimits {
            public long ProcessTime, JobTime; public uint LimitFlags; public UIntPtr MinWorkingSet, MaxWorkingSet;
            public uint ActiveLimit; public UIntPtr Affinity; public uint Priority, Scheduling;
        }
        [StructLayout(LayoutKind.Sequential)] private struct JobLimits {
            public BasicLimits Basic; public ulong ReadOps, WriteOps, OtherOps, ReadBytes, WriteBytes, OtherBytes;
            public UIntPtr ProcessMemory, JobMemory, PeakProcessMemory, PeakJobMemory;
        }
        [StructLayout(LayoutKind.Sequential)] private struct JobAccounting {
            public long UserTime, KernelTime, PeriodUserTime, PeriodKernelTime;
            public uint PageFaults, TotalProcesses, ActiveProcesses, TerminatedProcesses;
        }
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern IntPtr CreateJobObjectW(IntPtr security, string name);
        [DllImport("kernel32.dll", SetLastError = true)] private static extern bool SetInformationJobObject(IntPtr job, int kind, ref JobLimits info, int size);
        [DllImport("kernel32.dll", SetLastError = true)] private static extern bool QueryInformationJobObject(IntPtr job, int kind, ref JobAccounting info, int size, IntPtr length);
        [DllImport("kernel32.dll", SetLastError = true)] private static extern bool TerminateJobObject(IntPtr job, uint exit);
        [DllImport("kernel32.dll", SetLastError = true)] private static extern bool CreatePipe(out IntPtr read, out IntPtr write, ref Security security, uint size);
        [DllImport("kernel32.dll", SetLastError = true)] private static extern bool SetHandleInformation(IntPtr handle, uint mask, uint flags);
        [DllImport("kernel32.dll", SetLastError = true)] private static extern bool InitializeProcThreadAttributeList(IntPtr list, int count, int flags, ref IntPtr size);
        [DllImport("kernel32.dll", SetLastError = true)] private static extern bool UpdateProcThreadAttribute(IntPtr list, uint flags, IntPtr attribute, IntPtr value, IntPtr size, IntPtr previous, IntPtr returned);
        [DllImport("kernel32.dll")] private static extern void DeleteProcThreadAttributeList(IntPtr list);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern bool CreateProcessW(string file, StringBuilder command, IntPtr processSecurity, IntPtr threadSecurity, bool inherit, uint flags, IntPtr environment, string cwd, ref StartupEx startup, out ProcessInformation process);
        [DllImport("kernel32.dll", SetLastError = true)] private static extern uint ResumeThread(IntPtr thread);
        [DllImport("kernel32.dll")] private static extern uint WaitForSingleObject(IntPtr handle, uint milliseconds);
        [DllImport("kernel32.dll")] private static extern bool GetExitCodeProcess(IntPtr process, out uint code);
        [DllImport("kernel32.dll")] private static extern bool CloseHandle(IntPtr handle);
    }
}
