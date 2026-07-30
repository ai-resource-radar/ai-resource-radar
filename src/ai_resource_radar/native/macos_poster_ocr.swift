import Foundation
import ImageIO
import Vision

struct OCRPayload: Codable {
    let text: String
}

func fail(_ code: String) -> Never {
    FileHandle.standardError.write(Data("\(code)\n".utf8))
    exit(1)
}

guard CommandLine.arguments.count == 2 else {
    fail("poster_ocr_invalid_arguments")
}

let imageURL = URL(fileURLWithPath: CommandLine.arguments[1])
guard let source = CGImageSourceCreateWithURL(imageURL as CFURL, nil),
      let image = CGImageSourceCreateImageAtIndex(source, 0, nil)
else {
    fail("poster_ocr_invalid_image")
}

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = true
request.recognitionLanguages = ["zh-Hans", "en-US"]

let handler = VNImageRequestHandler(cgImage: image, options: [:])
do {
    try handler.perform([request])
} catch {
    fail("poster_ocr_request_failed")
}

let lines = (request.results ?? []).compactMap {
    $0.topCandidates(1).first?.string
}

do {
    let data = try JSONEncoder().encode(OCRPayload(text: lines.joined(separator: "\n")))
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data("\n".utf8))
} catch {
    fail("poster_ocr_encode_failed")
}
