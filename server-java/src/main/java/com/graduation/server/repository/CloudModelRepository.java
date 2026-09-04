package com.graduation.server.repository;

import com.graduation.server.entity.CloudModel;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;

public interface CloudModelRepository extends JpaRepository<CloudModel, Long> {

    List<CloudModel> findByOwnerOrderByCreatedAtDesc(String owner);

    Optional<CloudModel> findByIdAndOwner(Long id, String owner);
}
