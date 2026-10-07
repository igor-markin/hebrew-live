// Translate Hebrew lines from a text file with Apple Translation (on device) and time each call.
// Build: xcrun swiftc -parse-as-library -O -o apple_translate apple_translate.swift
// Run:   ./apple_translate sentences.txt [lowlatency]
// The input file is one sentence per line; the 12 synthetic references can be dumped with
//   python -c "import corpus; print('\n'.join(corpus.references()))" > sentences.txt
import Foundation
import Translation

@main
struct MT {
    static func main() async {
        let args = CommandLine.arguments
        guard args.count >= 2, let text = try? String(contentsOfFile: args[1], encoding: .utf8) else {
            print("usage: apple_translate <file> [lowlatency]"); return
        }
        let lowLatency = args.count >= 3 && args[2] == "lowlatency"
        let lines = text.split(separator: "\n").map(String.init)
        let he = Locale.Language(identifier: "he")
        for tgt in ["en", "ru"] {
            let t = Locale.Language(identifier: tgt)
            do {
                let session = lowLatency
                    ? try TranslationSession(installedSource: he, target: t, preferredStrategy: .lowLatency)
                    : try TranslationSession(installedSource: he, target: t)
                _ = try await session.translate("שלום.")   // warm-up
                let long = lines.joined(separator: " ")
                for (i, line) in (lines + [long]).enumerated() {
                    let t0 = DispatchTime.now().uptimeNanoseconds
                    let r = try await session.translate(line)
                    let ms = Double(DispatchTime.now().uptimeNanoseconds - t0) / 1e6
                    print("\(tgt)\t\(i == lines.count ? "ALL" : String(i + 1))\t\(String(format: "%.0f", ms)) ms\t\(r.targetText)")
                }
            } catch {
                print("\(tgt)\tERROR\t\(error)")
            }
        }
    }
}
