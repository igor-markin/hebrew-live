// Translate Hebrew sentences (one per line) with Apple Translation, on device, and time every call.
// Build: xcrun swiftc -parse-as-library -O -o apple_mt apple_mt.swift   (apple_mt.py builds it by itself)
// Run:   ./apple_mt en|ru sentences.txt [loop]
// Prints one JSON object per sentence: {"i": line index, "ms": call time, "text": translation}.
// `loop` repeats the file until the process is killed (used as background load for the ASR contention run).
// Only the default high-fidelity strategy serves Hebrew; .lowLatency rejects it (checked 2026-10-07).
import Foundation
import Translation

@main
struct AppleMT {
    static func emit(_ object: [String: Any]) {
        if let data = try? JSONSerialization.data(withJSONObject: object, options: [.withoutEscapingSlashes]),
           let line = String(data: data, encoding: .utf8) {
            print(line)
            fflush(stdout)
        }
    }

    static func main() async {
        let args = CommandLine.arguments
        guard args.count >= 3, ["en", "ru"].contains(args[1]),
              let text = try? String(contentsOfFile: args[2], encoding: .utf8) else {
            FileHandle.standardError.write(Data("usage: apple_mt en|ru sentences.txt [loop]\n".utf8))
            exit(2)
        }
        let loop = args.count >= 4 && args[3] == "loop"
        let lines = text.split(separator: "\n", omittingEmptySubsequences: false).map(String.init)
        do {
            let session = TranslationSession(installedSource: Locale.Language(identifier: "he"),
                                                 target: Locale.Language(identifier: args[1]))
            _ = try await session.translate("שלום.")   // warm-up, not reported
            repeat {
                for (i, line) in lines.enumerated() {
                    let began = DispatchTime.now().uptimeNanoseconds
                    do {
                        let result = try await session.translate(line)
                        let ms = Double(DispatchTime.now().uptimeNanoseconds - began) / 1e6
                        emit(["i": i, "ms": ms, "text": result.targetText])
                    } catch {
                        emit(["i": i, "error": "\(error)"])
                    }
                }
            } while loop
        } catch {
            FileHandle.standardError.write(Data("session failed: \(error)\n".utf8))
            exit(1)
        }
    }
}
