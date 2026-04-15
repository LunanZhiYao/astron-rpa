package com.iflytek.rpa.robot.controller;

import com.iflytek.rpa.robot.entity.dto.YunshangLunanSendDto;
import com.iflytek.rpa.robot.service.YunshangLunanMessageService;
import com.iflytek.rpa.utils.exception.NoLoginException;
import com.iflytek.rpa.utils.response.AppResponse;
import javax.annotation.Resource;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 云上鲁南消息：由服务端持有密钥与签名，客户端（RPA 执行器）仅传业务字段。
 */
@RestController
@RequestMapping("/yunshang-lunan")
public class YunshangLunanMessageController {

    @Resource
    private YunshangLunanMessageService yunshangLunanMessageService;

    @PostMapping("/send-message")
    public AppResponse<String> sendMessage(@RequestBody YunshangLunanSendDto dto) throws NoLoginException {
        return AppResponse.success(yunshangLunanMessageService.send(dto));
    }
}
