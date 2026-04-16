package com.iflytek.rpa.robot.controller;

import com.iflytek.rpa.robot.entity.vo.YunshangLunanUploadResultVo;
import com.iflytek.rpa.robot.service.YunshangLunanFileUploadService;
import com.iflytek.rpa.utils.response.AppResponse;
import javax.annotation.Resource;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

@RestController
@RequestMapping("/yunshang-lunan")
public class YunshangLunanFileUploadController {

    @Resource
    private YunshangLunanFileUploadService yunshangLunanFileUploadService;

    @PostMapping("/upload-file")
    public AppResponse<YunshangLunanUploadResultVo> upload(@RequestParam("file") MultipartFile file) {
        return AppResponse.success(yunshangLunanFileUploadService.upload(file));
    }
}
