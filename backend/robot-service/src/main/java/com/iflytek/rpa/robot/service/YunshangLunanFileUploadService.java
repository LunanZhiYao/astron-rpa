package com.iflytek.rpa.robot.service;

import com.iflytek.rpa.robot.entity.vo.YunshangLunanUploadResultVo;
import org.springframework.web.multipart.MultipartFile;

public interface YunshangLunanFileUploadService {
    YunshangLunanUploadResultVo upload(MultipartFile file);
}
