// Which languages do Apple Translation and Apple Speech support on this Mac? (macOS 26+)
// Build: xcrun swiftc -parse-as-library -O -o apple_probe apple_probe.swift
import Foundation
import Translation
import Speech

@main
struct Probe {
    static func main() async {
        let avail = LanguageAvailability()
        let langs = await avail.supportedLanguages
        let codes = langs.map { $0.minimalIdentifier }.sorted()
        print("TRANSLATION supportedLanguages (\(codes.count)):", codes.joined(separator: ","))
        let he = Locale.Language(identifier: "he"), en = Locale.Language(identifier: "en"), ru = Locale.Language(identifier: "ru")
        for (s, t, name) in [(he, en, "he->en"), (he, ru, "he->ru"), (en, ru, "en->ru")] {
            let st = await avail.status(from: s, to: t)
            print("TRANSLATION status \(name): \(st)")
        }
        if #available(macOS 26.0, *) {
            let locales = await SpeechTranscriber.supportedLocales
            print("SPEECH SpeechTranscriber.supportedLocales (\(locales.count)):",
                  locales.map { $0.identifier }.sorted().joined(separator: ","))
            let installed = await SpeechTranscriber.installedLocales
            print("SPEECH installedLocales:", installed.map { $0.identifier }.sorted().joined(separator: ","))
        } else {
            print("SPEECH: macOS < 26")
        }
    }
}
