import cv2
import numpy as np
import os
import sys
import glob


def detect_and_match(img1, img2):
    # SIFT로 특징점 검출
    sift = cv2.SIFT_create()
    kp1, des1 = sift.detectAndCompute(img1, None)
    kp2, des2 = sift.detectAndCompute(img2, None)

    # BFMatcher로 매칭
    bf = cv2.BFMatcher()
    matches = bf.knnMatch(des1, des2, k=2)

    # Lowe's ratio test로 좋은 매칭만 필터링
    good = []
    for m, n in matches:
        if m.distance < 0.75 * n.distance:
            good.append(m)

    pts1 = np.float32([kp1[m.queryIdx].pt for m in good])
    pts2 = np.float32([kp2[m.trainIdx].pt for m in good])

    return pts1, pts2, len(good)


def warp_and_merge(base, src, H):
    h1, w1 = base.shape[:2]
    h2, w2 = src.shape[:2]

    # 캔버스 크기 계산
    corners_src = np.float32([[0,0],[w2,0],[w2,h2],[0,h2]]).reshape(-1,1,2)
    corners_base = np.float32([[0,0],[w1,0],[w1,h1],[0,h1]]).reshape(-1,1,2)
    warped_corners = cv2.perspectiveTransform(corners_src, H)
    all_corners = np.concatenate([corners_base, warped_corners], axis=0)

    x_min, y_min = np.int32(all_corners.min(axis=0).ravel())
    x_max, y_max = np.int32(all_corners.max(axis=0).ravel())

    tx = -x_min
    ty = -y_min
    T = np.array([[1,0,tx],[0,1,ty],[0,0,1]], dtype=np.float64)

    out_w = x_max - x_min
    out_h = y_max - y_min

    warped_src = cv2.warpPerspective(src, T @ H, (out_w, out_h))
    warped_base = cv2.warpPerspective(base, T, (out_w, out_h))

    # 각 이미지의 마스크
    mask_src = (warped_src.sum(axis=2) > 0).astype(np.float32)
    mask_base = (warped_base.sum(axis=2) > 0).astype(np.float32)

    # distance transform으로 가중치 계산 (feathering blend)
    dist_src = cv2.distanceTransform((mask_src * 255).astype(np.uint8), cv2.DIST_L2, 5)
    dist_base = cv2.distanceTransform((mask_base * 255).astype(np.uint8), cv2.DIST_L2, 5)

    total = dist_src + dist_base + 1e-6
    alpha_src = (dist_src / total)[..., np.newaxis]
    alpha_base = (dist_base / total)[..., np.newaxis]

    result = warped_base.astype(np.float32) * alpha_base + warped_src.astype(np.float32) * alpha_src
    result = np.clip(result, 0, 255).astype(np.uint8)

    # 겹치지 않는 영역은 그냥 원본 사용
    only_base = ((mask_base == 1) & (mask_src == 0))[..., np.newaxis]
    only_src = ((mask_src == 1) & (mask_base == 0))[..., np.newaxis]
    result = np.where(only_base, warped_base, result)
    result = np.where(only_src, warped_src, result)

    return result


def load_images(path):
    if os.path.isdir(path):
        files = []
        for ext in ['*.jpg', '*.jpeg', '*.png']:
            files += glob.glob(os.path.join(path, ext))
        files = sorted(files)
    else:
        files = sorted(glob.glob(path))

    if len(files) < 2:
        print("이미지가 2장 이상 필요합니다.")
        sys.exit(1)

    imgs = []
    for f in files:
        img = cv2.imread(f)
        if img is None:
            print(f"읽기 실패: {f}")
            continue
        # 너무 크면 리사이즈
        h, w = img.shape[:2]
        if max(h, w) > 1500:
            scale = 1500 / max(h, w)
            img = cv2.resize(img, None, fx=scale, fy=scale)
        imgs.append(img)
        print(f"로드: {os.path.basename(f)} ({img.shape[1]}x{img.shape[0]})")

    return imgs


def stitch(images):
    panorama = images[0].copy()

    for i in range(1, len(images)):
        print(f"\n[{i}/{len(images)-1}] 정합 중...")

        gray1 = cv2.cvtColor(panorama, cv2.COLOR_BGR2GRAY)
        gray2 = cv2.cvtColor(images[i], cv2.COLOR_BGR2GRAY)

        pts1, pts2, n = detect_and_match(gray1, gray2)
        print(f"  매칭점: {n}개")

        if n < 10:
            print("  매칭점 부족, 건너뜀")
            continue

        H, mask = cv2.findHomography(pts2, pts1, cv2.RANSAC, 4.0)
        if H is None:
            print("  Homography 추정 실패")
            continue

        print(f"  inlier: {int(mask.sum())}개")
        panorama = warp_and_merge(panorama, images[i], H)
        print(f"  캔버스 크기: {panorama.shape[1]}x{panorama.shape[0]}")

    return panorama


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용법: python image_stitching.py <이미지 폴더>")
        print("예시: python image_stitching.py ./images/")
        sys.exit(1)

    path = sys.argv[1]
    output = sys.argv[2] if len(sys.argv) >= 3 else "panorama.jpg"

    print("=== Image Stitching ===")
    images = load_images(path)
    print(f"\n총 {len(images)}장 로드")

    result = stitch(images)
    cv2.imwrite(output, result)
    print(f"\n저장 완료: {output}")

    # 결과 미리보기
    try:
        preview = result.copy()
        h, w = preview.shape[:2]
        if max(h, w) > 1200:
            scale = 1200 / max(h, w)
            preview = cv2.resize(preview, None, fx=scale, fy=scale)
        cv2.imshow("Result", preview)
        cv2.waitKey(0)
        cv2.destroyAllWindows()
    except:
        pass