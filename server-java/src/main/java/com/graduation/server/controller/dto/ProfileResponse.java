package com.graduation.server.controller.dto;

public record ProfileResponse(
        String username,
        String nickname,
        String phone,
        String email
) {
}
