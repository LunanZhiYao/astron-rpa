package com.iflytek.rpa.robot.service;

import com.iflytek.rpa.robot.entity.dto.YunshangLunanSendDto;

public interface YunshangLunanMessageService {

    /**
     * 加密 text/link、按 ErpApi 规则签名并请求云上鲁南接口，返回对方响应体文本。
     */
    String send(YunshangLunanSendDto dto);
}
