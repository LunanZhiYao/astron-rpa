package com.iflytek.rpa.robot.service;

import com.iflytek.rpa.robot.entity.vo.MinioUploadResultVo;
import org.springframework.web.multipart.MultipartFile;

public interface MinioFileUploadService {
    MinioUploadResultVo upload(MultipartFile file, String objectName);
}
