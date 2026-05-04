from deepface import DeepFace
import json
import os

input_image = "./detect/1.png"  # your input image path
db_path = "./pics/"            # your database folder


def extract_name(path):
    """Get person name from subfolder: db/Alice/img1.jpg → Alice"""
    parts = path.replace("\\", "/").split("/")
    return parts[-2] if len(parts) >= 2 else os.path.splitext(parts[-1])[0]

def recognize_to_json(input_image, db_path, model_name="VGG-Face"):
    output = [input_image,]

    try:
        results = DeepFace.find(
            img_path=input_image,
            db_path=db_path,
            model_name=model_name,
            detector_backend="opencv",
            enforce_detection=True,
            threshold=0.4
        )

        for face_idx, df in enumerate(results):
            matches = []

            if not df.empty:
                for _, row in df.iterrows():
                    name = extract_name(row["identity"])
                    distance = round(float(row["distance"]), 4)
                    threshold = round(float(row["threshold"]), 4)
                    confidence = round((1 - distance / threshold) * 100, 2)
                    parts = row["identity"].replace("\\", "/")
                    matches.append({
                        "name": name,
                        "image_path": parts,
                        "distance": distance,
                        "threshold": threshold,
                        "confidence_pct": confidence,
                        "status": "match" if confidence >= 70 else "weak_match"
                    })

            output.append({
                "face_index": face_idx,
                "total_matches": len(matches),
                "matches": matches
            })

    except ValueError as e:
        output.append({
            "face_index": 0,
            "error": str(e),
            "total_matches": 0,
            "matches": []
        })

    return json.dumps(output, indent=2)


# # --- Run it ---
# result_json = recognize_to_json(input_image, db_path)
# print(result_json)