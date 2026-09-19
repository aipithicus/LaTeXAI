using System;
using System.Collections.Generic;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Threading.Tasks;

namespace LaTeXAI
{
    public sealed class FingerprintFile
    {
        public string Path { get; set; }
        public long Bytes { get; set; }
        public string Sha256 { get; set; }
    }

    public sealed class FingerprintTree
    {
        public string Sha256 { get; set; }
        public FingerprintFile[] Files { get; set; }
    }

    public static class TreeFingerprint
    {
        // Bound I/O concurrency within a verification pass. Each call reads every
        // byte afresh: neither timestamps nor previous fingerprints are a cache.
        private const int Readers = 4;

        public static FingerprintTree Read(string root)
        {
            var pending = new Stack<DirectoryInfo>();
            var paths = new Dictionary<string, FileInfo>(StringComparer.Ordinal);
            pending.Push(new DirectoryInfo(root));
            while (pending.Count != 0)
            {
                var directory = pending.Pop();
                RejectLink(directory);
                foreach (var item in directory.EnumerateFileSystemInfos())
                {
                    RejectLink(item);
                    if (item is DirectoryInfo child)
                    {
                        pending.Push(child);
                        continue;
                    }
                    var name = System.IO.Path.GetRelativePath(root, item.FullName).Replace('\\', '/');
                    paths.Add(name, (FileInfo)item);
                }
            }

            var names = new string[paths.Count];
            paths.Keys.CopyTo(names, 0);
            Array.Sort(names, StringComparer.Ordinal);
            var files = new FingerprintFile[names.Length];
            Parallel.For(0, names.Length, new ParallelOptions { MaxDegreeOfParallelism = Readers }, index =>
            {
                var name = names[index];
                var file = paths[name];
                var length = file.Length;
                string hash;
                using (var stream = new FileStream(file.FullName, FileMode.Open, FileAccess.Read,
                    FileShare.Read, 4096, FileOptions.SequentialScan))
                {
                    hash = Hex(SHA256.HashData(stream));
                }
                files[index] = new FingerprintFile { Path = name, Bytes = length, Sha256 = hash };
            });

            // Preserve the established ordinal UTF-8 path/NUL/size/NUL/hash/LF
            // stream exactly, independently of file-read completion order.
            var text = new StringBuilder();
            foreach (var file in files)
            {
                text.Append(file.Path).Append('\0').Append(file.Bytes).Append('\0').Append(file.Sha256).Append('\n');
            }
            return new FingerprintTree { Files = files, Sha256 = Hex(SHA256.HashData(Encoding.UTF8.GetBytes(text.ToString()))) };
        }

        private static string Hex(byte[] bytes) => Convert.ToHexString(bytes).ToLowerInvariant();

        private static void RejectLink(FileSystemInfo item)
        {
            if ((item.Attributes & FileAttributes.ReparsePoint) != 0)
                throw new IOException("Linked frozen input: " + item.FullName);
        }
    }
}
