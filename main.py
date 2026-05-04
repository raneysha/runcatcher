from deepface import DeepFace
import json
result = DeepFace.verify(img1_path = "./pics/1.png", img2_path = "./pics/duddin/2.png")
print(json.dumps(result))