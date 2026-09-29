import Foundation
import Vision
import ImageIO

struct OCRRow: Codable {
    let path: String
    let text: String
    let error: String?
}

func recognize(_ path: String) -> OCRRow {
    guard let source = CGImageSourceCreateWithURL(URL(fileURLWithPath: path) as CFURL, nil),
          let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
        return OCRRow(path: path, text: "", error: "无法读取图片")
    }
    var lines: [String] = []
    let request = VNRecognizeTextRequest { request, error in
        guard error == nil, let results = request.results as? [VNRecognizedTextObservation] else { return }
        lines = results.compactMap { $0.topCandidates(1).first?.string }
    }
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["zh-Hans", "en-US"]
    request.usesLanguageCorrection = true
    do {
        try VNImageRequestHandler(cgImage: image, options: [:]).perform([request])
        return OCRRow(path: path, text: lines.joined(separator: "\n"), error: nil)
    } catch {
        return OCRRow(path: path, text: "", error: String(describing: error))
    }
}

let encoder = JSONEncoder()
encoder.outputFormatting = [.withoutEscapingSlashes]
for path in CommandLine.arguments.dropFirst() {
    if let data = try? encoder.encode(recognize(path)), let line = String(data: data, encoding: .utf8) {
        print(line)
    }
}
