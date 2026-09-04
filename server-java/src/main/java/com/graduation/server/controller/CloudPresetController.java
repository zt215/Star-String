package com.graduation.server.controller;

import com.graduation.server.common.ApiResponse;
import com.graduation.server.controller.dto.CloudDeleteRequest;
import com.graduation.server.controller.dto.CloudPresetRequest;
import com.graduation.server.controller.dto.CloudPresetResponse;
import com.graduation.server.service.CloudPresetService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/cloud/presets")
public class CloudPresetController {

    private final CloudPresetService service;

    public CloudPresetController(CloudPresetService service) {
        this.service = service;
    }

    @PostMapping
    public ApiResponse<CloudPresetResponse> save(@RequestBody CloudPresetRequest request) {
        try {
            if (request == null) {
                throw new IllegalArgumentException("方案信息不能为空");
            }
            return ApiResponse.ok(service.save(request.owner(), request.kind(), request.name(), request.content()));
        } catch (IllegalArgumentException exception) {
            return ApiResponse.error(exception.getMessage());
        }
    }

    @GetMapping
    public ApiResponse<List<CloudPresetResponse>> list(
            @RequestParam("owner") String owner,
            @RequestParam(value = "kind", defaultValue = "config") String kind
    ) {
        return ApiResponse.ok(service.list(owner, kind));
    }

    @PostMapping("/delete")
    public ApiResponse<Void> delete(@RequestBody CloudDeleteRequest request) {
        try {
            if (request == null || request.id() == null || request.owner() == null || request.owner().isBlank()) {
                throw new IllegalArgumentException("删除参数不能为空");
            }
            service.delete(request.owner(), request.id());
            return ApiResponse.ok(null);
        } catch (IllegalArgumentException exception) {
            return ApiResponse.error(exception.getMessage());
        }
    }
}
